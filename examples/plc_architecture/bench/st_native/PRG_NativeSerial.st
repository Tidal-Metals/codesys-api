PROGRAM PRG_NativeSerial
// Bench, --serial native (generated from bench/st_native): the PLC's RJ12 port is polled by the device tree's
// Modbus_COM master, one server per unit, each channel mapped to GVL_Native.Unit<n>. Called in the bus task
// (the bus cycle task, which refreshes those images): hands each image to the same decode table as the
// ModbusFB lines and turns the server's xError into source health. The device tree gives no per-reply event,
// so SourceLastGoodMs means "no error flagged as of this cycle", not "a reply arrived". And xError only
// describes the latest poll: with auto-restart a dead server's flag clears at every retry (bench, 2026-10-20:
// unit 5 silent, healthy in a third of control scans with its last image), so a server counts as healthy only
// after HOLD_MS without an error.
VAR CONSTANT
	HOLD_MS : ULINT := 2500;            // longer than a channel cycle plus the reply timeout
END_VAR
VAR
	Words : ARRAY[0..124] OF WORD;
	Bits : ARRAY[0..1999] OF BYTE;
	WasError : ARRAY[1..@@COUNT@@] OF BOOL;
	ErrorEdges : ARRAY[1..@@COUNT@@] OF UDINT;     // diagnostics: times each server went into error
	ErrorCycles : ARRAY[1..@@COUNT@@] OF UDINT;    // ... and bus cycles it spent in error (share = / CycleCount)
	CycleCount : UDINT;
	LastErrorMs : ARRAY[1..@@COUNT@@] OF ULINT;
	NowMs : ULINT;
END_VAR
// ---- implementation ----
NowMs := F_NowMs();
CycleCount := CycleCount + 1;
@@CALLS@@
