// Symbols the desktop build gets from RT64 or from native-code-generating
// libraries that have no web equivalent.
//
// Mods: librecomp loads mods by recompiling their MIPS code to native code at
// runtime (N64Recomp's LiveRecomp / sljit). WebAssembly cannot generate and
// run new native code, so the web build has no mod support: these stubs make
// every live-recompile path fail cleanly, and nothing calls them unless a mod
// is installed, which the web build never has.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ostream>
#include <span>
#include <string>
#include <unordered_map>
#include <vector>

#include "recompiler/context.h"
#include "recompiler/live_recompiler.h"
#include <ultramodern/ultramodern.hpp>

extern "C" {
void RT64_SetUCodeOverride(uint32_t, const char*) {}

void RT64_GetTransformPairing(unsigned long long* frames, unsigned long long* total, unsigned long long* ignored,
                              unsigned long long* unpaired, unsigned long long* unpaired_moved) {
    *frames = *total = *ignored = *unpaired = *unpaired_moved = 0;
}
}

namespace {
[[noreturn]] void no_mods() {
    std::fprintf(stderr, "[web] mods are not supported in the web build\n");
    std::abort();
}
}  // namespace

namespace N64Recomp {
struct LiveGeneratorContext {};   // forward-declared in the header; empty here
void live_recompiler_init() {}

LiveGenerator::LiveGenerator(size_t, const LiveGeneratorInputs&) { no_mods(); }
LiveGenerator::~LiveGenerator() {}
LiveGeneratorOutput LiveGenerator::finish() { no_mods(); }
void LiveGenerator::process_binary_op(const BinaryOp&, const InstructionContext&) const { no_mods(); }
void LiveGenerator::process_unary_op(const UnaryOp&, const InstructionContext&) const { no_mods(); }
void LiveGenerator::process_store_op(const StoreOp&, const InstructionContext&) const { no_mods(); }
void LiveGenerator::emit_function_start(const std::string&, size_t) const { no_mods(); }
void LiveGenerator::emit_function_end() const { no_mods(); }
void LiveGenerator::emit_function_call_lookup(uint32_t) const { no_mods(); }
void LiveGenerator::emit_function_call_by_register(int) const { no_mods(); }
void LiveGenerator::emit_function_call_reference_symbol(const Context&, uint16_t, size_t, uint32_t) const { no_mods(); }
void LiveGenerator::emit_function_call(const Context&, size_t) const { no_mods(); }
void LiveGenerator::emit_named_function_call(const std::string&) const { no_mods(); }
void LiveGenerator::emit_goto(const std::string&) const { no_mods(); }
void LiveGenerator::emit_label(const std::string&) const { no_mods(); }
void LiveGenerator::emit_jtbl_addend_declaration(const JumpTable&, int) const { no_mods(); }
void LiveGenerator::emit_branch_condition(const ConditionalBranchOp&, const InstructionContext&) const { no_mods(); }
void LiveGenerator::emit_branch_close() const { no_mods(); }
void LiveGenerator::emit_switch(const Context&, const JumpTable&, int) const { no_mods(); }
void LiveGenerator::emit_case(int, const std::string&) const { no_mods(); }
void LiveGenerator::emit_switch_error(uint32_t, uint32_t) const { no_mods(); }
void LiveGenerator::emit_switch_close() const { no_mods(); }
void LiveGenerator::emit_return(const Context&, size_t) const { no_mods(); }
void LiveGenerator::emit_check_fr(int) const { no_mods(); }
void LiveGenerator::emit_check_nan(int, bool) const { no_mods(); }
void LiveGenerator::emit_cop0_status_read(int) const { no_mods(); }
void LiveGenerator::emit_cop0_status_write(int) const { no_mods(); }
void LiveGenerator::emit_cop1_cs_read(int) const { no_mods(); }
void LiveGenerator::emit_cop1_cs_write(int) const { no_mods(); }
void LiveGenerator::emit_muldiv(InstrId, int, int) const { no_mods(); }
void LiveGenerator::emit_syscall(uint32_t) const { no_mods(); }
void LiveGenerator::emit_do_break(uint32_t) const { no_mods(); }
void LiveGenerator::emit_pause_self() const { no_mods(); }
void LiveGenerator::emit_trigger_event(uint32_t) const { no_mods(); }
void LiveGenerator::emit_comment(const std::string&) const { no_mods(); }

LiveGeneratorOutput::~LiveGeneratorOutput() {}
size_t LiveGeneratorOutput::num_reference_symbol_jumps() const { return 0; }
void LiveGeneratorOutput::set_reference_symbol_jump(size_t, recomp_func_t*) { no_mods(); }
ReferenceJumpDetails LiveGeneratorOutput::get_reference_symbol_jump_details(size_t) { no_mods(); }
void LiveGeneratorOutput::populate_import_symbol_jumps(size_t, recomp_func_t*) { no_mods(); }

bool recompile_function_live(LiveGenerator&, const Context&, size_t, std::ostream&,
                             std::span<std::vector<uint32_t>>, bool) { return false; }

ShimFunction::ShimFunction(recomp_func_ext_t*, uintptr_t) { no_mods(); }
ShimFunction::~ShimFunction() {}

ModSymbolsError parse_mod_symbols(std::span<const char>, std::span<const uint8_t>,
                                  const std::unordered_map<uint32_t, uint16_t>&, Context&) {
    return ModSymbolsError::NotASymbolFile;
}
}  // namespace N64Recomp

// Browser threads have no settable names or priorities.
void ultramodern::set_native_thread_name(const std::string&) {}
void ultramodern::set_native_thread_priority(ultramodern::ThreadPriority) {}
