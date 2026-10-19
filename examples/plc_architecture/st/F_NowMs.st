FUNCTION F_NowMs : ULINT
// Monotonic milliseconds since start-up, for ages and timeouts. Not wall-clock time.
VAR
	Microseconds : ULINT;
END_VAR
// ---- implementation ----
SysTimeCore.SysTimeGetUs(pUsTime := Microseconds);
F_NowMs := Microseconds / 1000;
