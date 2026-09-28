/* Minimal POSIX layer for building ido-static-recomp's libc_impl.c natively on
 * Windows (clang targeting x86_64-pc-windows-msvc). Only what cfe, uopt, ugen
 * and as1 need; process control (fork/exec/wait/kill/pipe) is stubbed because
 * tools/idowin/ido_cc.py drives the passes itself instead of IDO's cc. */
#pragma once
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#include <direct.h>
#include <process.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/utime.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
#include <stdint.h>

typedef intptr_t ssize_t;
typedef int pid_t;
typedef unsigned int mode_t;
typedef long long off64_t;

#ifndef PATH_MAX
#define PATH_MAX 260
#endif

#define open _open
#define close _close
#define read(fd, buf, n) _read((fd), (buf), (unsigned)(n))
#define write(fd, buf, n) _write((fd), (buf), (unsigned)(n))
#define lseek _lseek
#define unlink _unlink
#define access _access
#define creat(p, m) _open((p), _O_CREAT | _O_TRUNC | _O_WRONLY | _O_BINARY, _S_IREAD | _S_IWRITE)
#define dup _dup
#define dup2 _dup2
#define isatty _isatty
#define getpid _getpid
#define getcwd _getcwd
#define chmod _chmod
#define umask _umask
#define ftruncate _chsize
#define utime _utime
#define utimbuf _utimbuf
#define mktemp _mktemp

#ifndef O_ACCMODE
#define O_ACCMODE (_O_RDONLY | _O_WRONLY | _O_RDWR)
#endif
#define O_NOCTTY 0
#define F_OK 0
#define R_OK 4
#define W_OK 2
#define X_OK 0

/* ---- mmap ---------------------------------------------------------------- */
#define PROT_NONE 0
#define PROT_READ 1
#define PROT_WRITE 2
#define PROT_EXEC 4
#define MAP_SHARED 1
#define MAP_PRIVATE 2
#define MAP_FIXED 0x10
#define MAP_ANONYMOUS 0x20
#define MAP_NORESERVE 0x4000
#define MAP_FAILED ((void*)-1)

#define PW_MAX_FILE_MAPS 64
static struct { void* p; size_t n; } pw_file_maps[PW_MAX_FILE_MAPS];

static inline void* mmap(void* addr, size_t len, int prot, int flags, int fd, long long off) {
    (void)prot;
    if (flags & MAP_ANONYMOUS) {
        if (addr == NULL) {
            /* The guest region: reserve and commit up front (pages are demand-zero). */
            void* p = VirtualAlloc(NULL, len, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
            return p ? p : MAP_FAILED;
        }
        /* A fixed range inside the already-committed guest region. */
        memset(addr, 0, len);
        return addr;
    }
    /* File mapping: a private copy is all libc_impl needs. */
    void* p = calloc(1, len ? len : 1);
    if (!p) return MAP_FAILED;
    long long saved = _lseeki64(fd, 0, SEEK_CUR);
    _lseeki64(fd, off, SEEK_SET);
    size_t got = 0;
    while (got < len) {
        int r = _read(fd, (char*)p + got, (unsigned)(len - got));
        if (r <= 0) break;
        got += (size_t)r;
    }
    _lseeki64(fd, saved, SEEK_SET);
    for (int i = 0; i < PW_MAX_FILE_MAPS; i++) {
        if (!pw_file_maps[i].p) { pw_file_maps[i].p = p; pw_file_maps[i].n = len; break; }
    }
    return p;
}

static inline int munmap(void* addr, size_t len) {
    (void)len;
    for (int i = 0; i < PW_MAX_FILE_MAPS; i++) {
        if (pw_file_maps[i].p == addr) { free(addr); pw_file_maps[i].p = NULL; return 0; }
    }
    return VirtualFree(addr, 0, MEM_RELEASE) ? 0 : 0;
}

static inline int mprotect(void* addr, size_t len, int prot) { (void)addr; (void)len; (void)prot; return 0; }

/* ---- misc ---------------------------------------------------------------- */
#define _SC_PAGESIZE 30
#define _PC_PATH_MAX 4
static inline long sysconf(int name) { (void)name; return 4096; }
static inline long pathconf(const char* p, int name) { (void)p; (void)name; return PATH_MAX; }

static inline ssize_t readlink(const char* path, char* buf, size_t n) {
    if (strcmp(path, "/proc/self/exe") == 0) {
        DWORD r = GetModuleFileNameA(NULL, buf, (DWORD)n);
        if (r == 0 || r >= n) return -1;
        for (DWORD i = 0; i < r; i++) if (buf[i] == '\\') buf[i] = '/';
        return (ssize_t)r;
    }
    errno = EINVAL;
    return -1;
}

static inline char* dirname(char* path) {
    char* s = strrchr(path, '/');
    char* b = strrchr(path, '\\');
    if (b > s) s = b;
    if (!s) { strcpy(path, "."); return path; }
    if (s == path) { s[1] = 0; return path; }
    *s = 0;
    return path;
}

static inline char* basename(char* path) {
    char* s = strrchr(path, '/');
    char* b = strrchr(path, '\\');
    if (b > s) s = b;
    return s ? s + 1 : path;
}

static inline int truncate(const char* path, long long len) {
    int fd = _open(path, _O_WRONLY | _O_BINARY);
    if (fd < 0) return -1;
    int r = _chsize_s(fd, len) == 0 ? 0 : -1;
    _close(fd);
    return r;
}

static inline int mkstemp(char* tmpl) {
    if (_mktemp_s(tmpl, strlen(tmpl) + 1) != 0) return -1;
    return _open(tmpl, _O_CREAT | _O_EXCL | _O_RDWR | _O_BINARY, _S_IREAD | _S_IWRITE);
}

struct tms { clock_t tms_utime, tms_stime, tms_cutime, tms_cstime; };
static inline clock_t times(struct tms* t) {
    clock_t c = clock();
    t->tms_utime = c; t->tms_stime = 0; t->tms_cutime = 0; t->tms_cstime = 0;
    return c;
}

/* Process control is not used when the passes are driven directly. */
static inline int fork(void) { errno = ENOSYS; return -1; }
static inline int pipe(int fds[2]) { return _pipe(fds, 4096, _O_BINARY); }
static inline pid_t wait(int* st) { (void)st; errno = ECHILD; return -1; }
static inline int kill(pid_t pid, int sig) { (void)pid; (void)sig; errno = ENOSYS; return -1; }
#define execv(p, a) _execv((p), (const char* const*)(a))
#define execvp(p, a) _execvp((p), (const char* const*)(a))
#define WIFEXITED(s) 1
#define WEXITSTATUS(s) (s)

#ifndef SIGPIPE
#define SIGPIPE 13
#endif

/* ---- getopt (POSIX semantics, single-character options) ------------------ */
static char* optarg = NULL;
static int optind = 1, opterr = 1, optopt = 0;
static int pw_optpos = 1;

static inline int getopt(int argc, char* const argv[], const char* optstring) {
    optarg = NULL;
    if (optind >= argc || argv[optind] == NULL || argv[optind][0] != '-' || argv[optind][1] == '\0') {
        return -1;
    }
    if (strcmp(argv[optind], "--") == 0) {
        optind++;
        return -1;
    }
    int c = (unsigned char)argv[optind][pw_optpos];
    const char* spec = strchr(optstring, c);
    optopt = c;
    if (spec == NULL || c == ':') {
        if (opterr && optstring[0] != ':') fprintf(stderr, "%s: illegal option -- %c\n", argv[0], c);
        if (argv[optind][++pw_optpos] == '\0') { optind++; pw_optpos = 1; }
        return '?';
    }
    if (spec[1] == ':') {
        if (argv[optind][pw_optpos + 1] != '\0') {
            optarg = &argv[optind][pw_optpos + 1];
        } else if (optind + 1 < argc) {
            optarg = argv[++optind];
        } else {
            optind++;
            pw_optpos = 1;
            if (opterr && optstring[0] != ':') fprintf(stderr, "%s: option requires an argument -- %c\n", argv[0], c);
            return optstring[0] == ':' ? ':' : '?';
        }
        optind++;
        pw_optpos = 1;
        return c;
    }
    if (argv[optind][++pw_optpos] == '\0') { optind++; pw_optpos = 1; }
    return c;
}

/* ---- rarely used by the passes; minimal stand-ins ------------------------ */
static inline int flock(int fd, int op) { (void)fd; (void)op; return 0; }
static inline int fchown(int fd, int uid, int gid) { (void)fd; (void)uid; (void)gid; return 0; }
static inline int getpgrp(void) { return _getpid(); }
static inline int gethostname(char* name, size_t len) {
    if (len) { strncpy(name, "localhost", len); name[len - 1] = 0; }
    return 0;
}
typedef void (*pw_sighandler_t)(int);
static inline pw_sighandler_t sigset(int sig, pw_sighandler_t h) { (void)sig; (void)h; return (pw_sighandler_t)0; }
static inline void __assert(const char* expr, const char* file, int line) {
    fprintf(stderr, "Assertion failed: %s, file %s, line %d\n", expr, file, line);
    abort();
}

/* ---- process-unique temporary names -------------------------------------
 * MSVC's tmpnam/_tempnam are not unique across processes started together,
 * which corrupts parallel builds; name temp files after the PID instead. */
static unsigned pw_tmp_counter = 0;
static inline char* pw_tmpname(char* buf, const char* dir, const char* pfx) {
    static char local[PATH_MAX];
    char base[PATH_MAX];
    if (!buf) buf = local;
    if (!dir || !*dir) {
        DWORD n = GetTempPathA(PATH_MAX, base);
        if (n == 0 || n >= PATH_MAX) strcpy(base, ".\\");
        dir = base;
    }
    snprintf(buf, PATH_MAX, "%s%s%s%lu_%u", dir,
             (dir[strlen(dir) - 1] == '\\' || dir[strlen(dir) - 1] == '/') ? "" : "/",
             pfx ? pfx : "ido", (unsigned long)GetCurrentProcessId(), pw_tmp_counter++);
    return buf;
}
#define tmpnam(b) pw_tmpname((b), NULL, "ido")
static inline char* tempnam(const char* dir, const char* pfx) {
    char* out = (char*)malloc(PATH_MAX);
    return out ? pw_tmpname(out, dir, pfx) : NULL;
}
