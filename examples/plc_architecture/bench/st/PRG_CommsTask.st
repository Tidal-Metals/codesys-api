PROGRAM PRG_CommsTask
// Body of the comms task on the two-task bench (CommsTask: cyclic, priority below the control task):
// PRG_Comms, timed. ExecUs is wall time from start to end of this task's scan, so it includes any time the
// control task preempted it. A publish is timed from PRG_Comms.IsRequested going TRUE to FALSE (done).
VAR
	IsEnabled : BOOL := TRUE;
	ResetStats : BOOL;

	ScanCount : UDINT;
	ExecUs : UDINT;
	MaxExecUs : UDINT;
	ExecTotalUs : ULINT;
	MaxIntervalUs : UDINT;
	PublishCount : UDINT;
	LastPublishUs : UDINT;
	MaxPublishUs : UDINT;
	LastPayloadLength : UDINT;
	MaxClientCalls : INT;

	StartUs : ULINT;
	PreviousStartUs : ULINT;
	RequestUs : ULINT;
	WasRequested : BOOL;
END_VAR
// ---- implementation ----
StartUs := F_NowUs();
IF ResetStats THEN
	ResetStats := FALSE;
	ScanCount := 0;
	MaxExecUs := 0;
	ExecTotalUs := 0;
	MaxIntervalUs := 0;
	PublishCount := 0;
	MaxPublishUs := 0;
	MaxClientCalls := 0;
	PreviousStartUs := 0;
END_IF
IF PreviousStartUs <> 0 THEN
	MaxIntervalUs := MAX(MaxIntervalUs, ULINT_TO_UDINT(StartUs - PreviousStartUs));
END_IF
PreviousStartUs := StartUs;

IF IsEnabled THEN
	PRG_Comms();
	MaxClientCalls := MAX(MaxClientCalls, PRG_Comms.ClientCall);
	IF PRG_Comms.IsRequested AND NOT WasRequested THEN
		RequestUs := StartUs;
		LastPayloadLength := PRG_Comms.Used;
	ELSIF WasRequested AND NOT PRG_Comms.IsRequested THEN
		LastPublishUs := ULINT_TO_UDINT(StartUs - RequestUs);
		MaxPublishUs := MAX(MaxPublishUs, LastPublishUs);
		PublishCount := PublishCount + 1;
	END_IF
	WasRequested := PRG_Comms.IsRequested;
END_IF

ExecUs := ULINT_TO_UDINT(F_NowUs() - StartUs);
MaxExecUs := MAX(MaxExecUs, ExecUs);
ExecTotalUs := ExecTotalUs + ExecUs;
ScanCount := ScanCount + 1;
