"""A stand-in for IDO 5.3's `cc -c`, driving the recompiled passes directly.

IDO's cc forks and execs each pass; that cannot be emulated natively on
Windows, so this reproduces the pass pipelines cc runs (captured with
`cc -v` from the reference build) for the flag sets the decomp uses:
  -O1/-O2:  cfe -> [uopt] -> ugen -> as1
  -O3:      cfe -> ujoin -> uld -> usplit -> umerge -> uopt -> ugen -> as1
Only the verbose-mode flags (-Xv, -verbose) are left out, which change what
the passes print, not what they produce.

    python ido_cc.py -c [cc flags...] -o out.o in.c
The passes are looked up in IDO_BIN (default: this script's ../../build/idowin).
"""
import os
import subprocess
import sys
import tempfile

PREDEFS = ("-D_MIPS_FPSET=16 -D_MIPS_ISA={isa} -D_ABIO32=1 -D_MIPS_SIM=_ABIO32 -D_MIPS_SZINT=32 "
           "-D_MIPS_SZLONG=32 -D_MIPS_SZPTR=32 -D__EXTENSIONS__ -DLANGUAGE_C -D_LANGUAGE_C "
           "-D__INLINE_INTRINSICS -Dsgi -D__sgi -Dunix -Dmips -Dhost_mips -D__unix -D__host_mips "
           "-D_SVR4_SOURCE -D_MODERN_C -D_SGI_SOURCE -D__DSO__ -DSYSTYPE_SVR4 -D_SYSTYPE_SVR4 "
           "-D_LONGLONG -D__mips={isa}")


def die(msg):
    sys.stderr.write(f"ido_cc: {msg}\n")
    sys.exit(1)


def parse(argv):
    o = {"opt": "-O1", "isa": 1, "g": "0", "defs_incs": [], "fullwarn": False, "woff": [],
         "cpluscomm": False, "nostdinc": False, "r4300_mul": False, "out": None, "src": None,
         "G": "0"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "-c" or a == "-non_shared" or a == "-32":
            pass
        elif a == "-G":
            i += 1
            o["G"] = argv[i]
        elif a in ("-O0", "-O1", "-O2", "-O3"):
            o["opt"] = a
        elif a.startswith("-mips"):
            o["isa"] = int(a[5:])
        elif a == "-g":
            o["g"] = "2"
        elif a.startswith("-g") and a[2:].isdigit():
            o["g"] = a[2:]
        elif a.startswith("-D") or a.startswith("-U"):
            o["defs_incs"].append(a if len(a) > 2 else a + argv[i + 1])
            if len(a) == 2:
                i += 1
        elif a.startswith("-I"):
            o["defs_incs"].append(a if len(a) > 2 else a + argv[i + 1])
            if len(a) == 2:
                i += 1
        elif a == "-fullwarn":
            o["fullwarn"] = True
        elif a == "-woff":
            i += 1
            o["woff"].append(argv[i])
        elif a == "-Xcpluscomm":
            o["cpluscomm"] = True
        elif a == "-nostdinc":
            o["nostdinc"] = True
        elif a == "-Wab,-r4300_mul":
            o["r4300_mul"] = True
        elif a == "-o":
            i += 1
            o["out"] = argv[i]
        elif a.endswith(".c") or a.endswith(".i"):
            o["src"] = a
        else:
            die(f"unsupported flag {a}")
        i += 1
    if not o["src"] or not o["out"]:
        die("need -o <out.o> and a source file")
    return o


def main(argv):
    o = parse(argv[1:])
    bindir = os.environ.get("IDO_BIN") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "build", "idowin")
    exe = lambda n: os.path.join(bindir, n + ".exe")
    isa = o["isa"]
    mips = [] if isa == 1 else [f"-mips{isa}"]
    g = ["-g" + o["g"]]
    opt = o["opt"]
    dw = ["-dwopcode"] if isa == 3 else []
    tmp = tempfile.mkdtemp(prefix="ido_")
    T = lambda n: os.path.join(tmp, n)
    symtab, ucode = T("st"), T("f")

    # cc passes the user's -I first, then its own endianness/STDC defines,
    # then the user's -D/-U, each group in command-line order.
    user = o["defs_incs"]
    cfe = [exe("cfe")] + PREDEFS.format(isa=isa).split()
    incs = [x for x in user if x.startswith("-I")]
    defs = [x for x in user if not x.startswith("-I")]
    cfe += (["-I"] if o["nostdinc"] else []) + incs + ["-D_MIPSEB", "-DMIPSEB", "-D__STDC__=1"]
    if not o["nostdinc"]:
        cfe += ["-I/usr/include"]
    cfe += defs + [o["src"], "-D_CFE", "-Amachine(mips)", "-Asystem(unix)"]
    if o["fullwarn"]:
        cfe += ["-Xfullwarn"]
    for w in o["woff"]:
        cfe += ["-Xwoff" + w]
    cfe += ["-non_shared"]
    if o["fullwarn"]:
        cfe += ["-wimplicit"]
    cfe += ["-G", o["G"], "-std", "-XS" + symtab]
    if o["cpluscomm"]:
        cfe += ["-Xcpluscomm"]
    cfe += mips + ["-EB", "-X" + g[0][1:]] + dw + [opt]
    if o["g"] != "0":
        cmdfile = T("cmd")
        with open(cmdfile, "w") as f:
            f.write("cc " + " ".join(argv[1:]) + "\n")
        cfe += ["-Xcmd:" + cmdfile]

    steps = [(cfe, ucode)]
    cur = ucode
    olimit = ["-Olimit", "5000"] if opt == "-O3" else []
    if opt == "-O3":
        # cc names the joined u-code after the source, relative to the cwd.
        u = os.path.splitext(os.path.basename(o["src"]))[0] + ".u"
        steps.append(([exe("ujoin")] + mips + ["-o", u, cur, symtab], None))
        lnk = T("l")
        steps.append(([exe("uld"), "-L/usr/lib/mips%d/nonshared" % isa, "-_SYSTYPE_SVR4", "-non_shared"] + mips +
                      g + ["-no_AutoGnum", "-preserve_dead_code", u, "-ko", lnk], None))
        spl = T("s")
        steps.append(([exe("usplit")] + mips + ["-o", spl, "-t", symtab, lnk], None))
        mrg = T("m")
        steps.append(([exe("umerge")] + olimit + mips + ["-EB"] + g + [opt, spl, "-o", mrg, "-t", symtab], None))
        cur = mrg
    if opt in ("-O2", "-O3"):
        uo = T("o")
        steps.append(([exe("uopt"), "-G", o["G"]] + olimit + mips + ["-EB"] + g + dw + [opt, cur, uo, "-t", symtab, T("os")], None))
        cur = uo
    asm = T("c")
    steps.append(([exe("ugen"), "-G", o["G"]] + mips + ["-EB"] + g + dw + [opt, cur, "-o", asm, "-t", symtab, "-temp", T("gt")], None))
    as1 = [exe("as1"), "-elf", "-G", o["G"], "-p0"]
    if o["r4300_mul"]:
        as1 += ["-r4300_mul", "-r4300_mul"]
    as1 += mips + ["-EB"] + g + dw + [opt] + olimit + [asm, "-o", o["out"], "-t", symtab]
    steps.append((as1, None))

    # cfe runs in the caller's directory (the source path and -I. are relative
    # to it); the later passes run in the private temp directory, because the
    # -O3 linker passes write fixed-name scratch files into their cwd and
    # parallel builds would otherwise trample each other.
    out_abs = os.path.abspath(o["out"])
    try:
        for n, (cmd, stdout_to) in enumerate(steps):
            cmd = [out_abs if c == o["out"] else c for c in cmd]
            cwd = None if n == 0 else tmp
            if stdout_to:
                with open(stdout_to, "wb") as f:
                    r = subprocess.run(cmd, stdout=f, cwd=cwd)
            else:
                r = subprocess.run(cmd, cwd=cwd)
            if r.returncode != 0:
                die(f"pass failed ({r.returncode}): {' '.join(cmd)}")
    finally:
        for n in os.listdir(tmp):
            os.remove(os.path.join(tmp, n))
        os.rmdir(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
