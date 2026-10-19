FUNCTION NowUs : ULINT
// Monotonic microsecond clock for the performance counters.
VAR
	Microseconds : ULINT;
END_VAR
// ---- implementation ----
SysTimeCore.SysTimeGetUs(pUsTime := Microseconds);
NowUs := Microseconds;
