FUNCTION F_NowUs : ULINT
// Monotonic microseconds since start-up, for time budgets within a scan. Not wall-clock time.
VAR
	Microseconds : ULINT;
END_VAR
// ---- implementation ----
SysTimeCore.SysTimeGetUs(pUsTime := Microseconds);
F_NowUs := Microseconds;
