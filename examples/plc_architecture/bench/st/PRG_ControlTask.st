PROGRAM PRG_ControlTask
// Body of the control task on the two-task bench (MainTask: cyclic 50 ms, priority 1): simulated inputs,
// then the control pipeline, timed. IntervalUs is the start-to-start time of this task; its deviation from
// NominalUs is the jitter the comms task could cause. ExecUs is the time spent in the task.
VAR
	NominalUs : ULINT := 50000;         // the task's configured interval
	ResetStats : BOOL;
	IsQualityCountRequested : BOOL;     // count tags per quality once (costs a pass over the table)

	ScanCount : UDINT;
	IntervalUs : UDINT;
	MinIntervalUs : UDINT := 16#FFFFFFFF;
	MaxIntervalUs : UDINT;
	MaxDeviationUs : UDINT;             // largest |IntervalUs - NominalUs|
	// |IntervalUs - NominalUs| in bands: <= 0.1 ms, 0.5 ms, 1 ms, 2 ms, 5 ms, more
	Deviation : ARRAY[0..5] OF UDINT;
	ExecUs : UDINT;
	MaxExecUs : UDINT;
	ExecTotalUs : ULINT;
	SimUs : UDINT;
	MaxSimUs : UDINT;
	GoodCount : INT;
	NotGoodCount : INT;

	StartUs : ULINT;
	PreviousStartUs : ULINT;
	StepUs : ULINT;
	DeviationUs : UDINT;
	Index : INT;
END_VAR
// ---- implementation ----
StartUs := F_NowUs();
IF ResetStats THEN
	ResetStats := FALSE;
	ScanCount := 0;
	MinIntervalUs := 16#FFFFFFFF;
	MaxIntervalUs := 0;
	MaxDeviationUs := 0;
	FOR Index := 0 TO 5 DO
		Deviation[Index] := 0;
	END_FOR
	MaxExecUs := 0;
	ExecTotalUs := 0;
	MaxSimUs := 0;
	PreviousStartUs := 0;
END_IF
IF PreviousStartUs <> 0 THEN
	IntervalUs := ULINT_TO_UDINT(StartUs - PreviousStartUs);
	MinIntervalUs := MIN(MinIntervalUs, IntervalUs);
	MaxIntervalUs := MAX(MaxIntervalUs, IntervalUs);
	IF UDINT_TO_ULINT(IntervalUs) >= NominalUs THEN
		DeviationUs := IntervalUs - ULINT_TO_UDINT(NominalUs);
	ELSE
		DeviationUs := ULINT_TO_UDINT(NominalUs) - IntervalUs;
	END_IF
	MaxDeviationUs := MAX(MaxDeviationUs, DeviationUs);
	IF DeviationUs <= 100 THEN
		Deviation[0] := Deviation[0] + 1;
	ELSIF DeviationUs <= 500 THEN
		Deviation[1] := Deviation[1] + 1;
	ELSIF DeviationUs <= 1000 THEN
		Deviation[2] := Deviation[2] + 1;
	ELSIF DeviationUs <= 2000 THEN
		Deviation[3] := Deviation[3] + 1;
	ELSIF DeviationUs <= 5000 THEN
		Deviation[4] := Deviation[4] + 1;
	ELSE
		Deviation[5] := Deviation[5] + 1;
	END_IF
END_IF
PreviousStartUs := StartUs;

StepUs := F_NowUs();
PRG_SimInputs();
SimUs := ULINT_TO_UDINT(F_NowUs() - StepUs);
MaxSimUs := MAX(MaxSimUs, SimUs);

PRG_Control();

IF IsQualityCountRequested THEN
	IsQualityCountRequested := FALSE;
	GoodCount := 0;
	NotGoodCount := 0;
	FOR Index := 1 TO GVL_Tags.TAG_COUNT DO
		IF GVL_Tags.Tags[Index].Quality = E_Quality.GOOD THEN
			GoodCount := GoodCount + 1;
		ELSE
			NotGoodCount := NotGoodCount + 1;
		END_IF
	END_FOR
END_IF

ExecUs := ULINT_TO_UDINT(F_NowUs() - StartUs);
MaxExecUs := MAX(MaxExecUs, ExecUs);
ExecTotalUs := ExecTotalUs + ExecUs;
ScanCount := ScanCount + 1;
