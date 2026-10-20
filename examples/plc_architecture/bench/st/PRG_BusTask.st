PROGRAM PRG_BusTask
// Body of the bus task on the bench (BusTask: cyclic 5 ms, priority between control and comms): PRG_Bus, timed.
// ExecUs is wall time, so it includes time the control task preempted it. Per line: requests and errors per
// second over the last full second, and how long the slowest request took.
VAR
	ResetStats : BOOL;
	ScanCount : UDINT;
	ExecUs : UDINT;
	MaxExecUs : UDINT;
	ExecTotalUs : ULINT;
	MaxIntervalUs : UDINT;
	RequestsPerSecond : ARRAY[1..GVL_Bus.LINE_COUNT] OF UDINT;
	ErrorsPerSecond : ARRAY[1..GVL_Bus.LINE_COUNT] OF UDINT;

	StartUs : ULINT;
	PreviousStartUs : ULINT;
	SecondStartUs : ULINT;
	RequestsAtSecond : ARRAY[1..GVL_Bus.LINE_COUNT] OF UDINT;
	ErrorsAtSecond : ARRAY[1..GVL_Bus.LINE_COUNT] OF UDINT;
	Index : INT;
END_VAR
// ---- implementation ----
StartUs := F_NowUs();
IF ResetStats THEN
	ResetStats := FALSE;
	ScanCount := 0;
	MaxExecUs := 0;
	ExecTotalUs := 0;
	MaxIntervalUs := 0;
	PreviousStartUs := 0;
END_IF
IF PreviousStartUs <> 0 THEN
	MaxIntervalUs := MAX(MaxIntervalUs, ULINT_TO_UDINT(StartUs - PreviousStartUs));
END_IF
PreviousStartUs := StartUs;

PRG_Bus();
PRG_SerialProbe();       // idle unless IsEnabled

IF StartUs - SecondStartUs >= 1000000 THEN
	SecondStartUs := StartUs;
	FOR Index := 1 TO GVL_Bus.LINE_COUNT DO
		RequestsPerSecond[Index] := PRG_Bus.Lines[Index].RequestCount - RequestsAtSecond[Index];
		ErrorsPerSecond[Index] := PRG_Bus.Lines[Index].ErrorCount - ErrorsAtSecond[Index];
		RequestsAtSecond[Index] := PRG_Bus.Lines[Index].RequestCount;
		ErrorsAtSecond[Index] := PRG_Bus.Lines[Index].ErrorCount;
	END_FOR
END_IF

ExecUs := ULINT_TO_UDINT(F_NowUs() - StartUs);
MaxExecUs := MAX(MaxExecUs, ExecUs);
ExecTotalUs := ExecTotalUs + ExecUs;
ScanCount := ScanCount + 1;
