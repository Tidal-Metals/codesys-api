METHOD FinishRequest : BOOL
// The active request finished: take its result, update the device's health and schedule the block again.
// A device that failed FAIL_LIMIT times in a row is COMM_FAIL and polled only every BACKOFF_MS.
VAR
	Source : INT;
END_VAR
// ---- implementation ----
LastRequestUs := ULINT_TO_UDINT(F_NowUs() - StartUs);
MaxRequestUs := MAX(MaxRequestUs, LastRequestUs);
RequestCount := RequestCount + 1;
IF IsError THEN
	ErrorCount := ErrorCount + 1;
END_IF

IF ActiveWrite <> 0 THEN
	IF IsDone THEN
		GVL_Bus.WriteCount[ActiveWrite] := GVL_Bus.WriteCount[ActiveWrite] + 1;
		WriteDueMs[ActiveWrite] := NowMs + GVL_Bus.Writes[ActiveWrite].RefreshMs;
	ELSE
		GVL_Bus.WriteErrors[ActiveWrite] := GVL_Bus.WriteErrors[ActiveWrite] + 1;
		WriteDueMs[ActiveWrite] := NowMs + 1000;     // retried in a second, not every call
	END_IF
	HasWritten[ActiveWrite] := TRUE;
	WriteSentValue[ActiveWrite] := WriteValue;
	CallRequest(IsExecute := FALSE);
	ActiveWrite := 0;
	FinishRequest := TRUE;
	RETURN;
END_IF

Source := Block.Source;
IF IsDone THEN
	GVL_Bus.SourceWriting[Source] := TRUE;
	Decode();
	GVL_Bus.SourceLastGoodMs[Source] := NowMs;
	GVL_Bus.SourceHealthy[Source] := TRUE;
	GVL_Bus.SourceFailCount[Source] := 0;
	GVL_Bus.SourceWriting[Source] := FALSE;
	GVL_Bus.BlockReads[ActiveBlock] := GVL_Bus.BlockReads[ActiveBlock] + 1;
	BlockDueMs[ActiveBlock] := NowMs + Block.PeriodMs;
ELSE
	GVL_Bus.BlockErrors[ActiveBlock] := GVL_Bus.BlockErrors[ActiveBlock] + 1;
	GVL_Bus.BlockLastError[ActiveBlock] := ErrorId;
	GVL_Bus.BlockLastException[ActiveBlock] := Exception;
	IF GVL_Bus.SourceFailCount[Source] < 65535 THEN
		GVL_Bus.SourceFailCount[Source] := GVL_Bus.SourceFailCount[Source] + 1;
	END_IF
	IF GVL_Bus.SourceFailCount[Source] >= GVL_Bus.FAIL_LIMIT THEN
		GVL_Bus.SourceWriting[Source] := TRUE;
		GVL_Bus.SourceHealthy[Source] := FALSE;
		GVL_Bus.SourceWriting[Source] := FALSE;
		BlockDueMs[ActiveBlock] := NowMs + MAX(Block.PeriodMs, GVL_Bus.BACKOFF_MS);
	ELSE
		BlockDueMs[ActiveBlock] := NowMs + Block.PeriodMs;
	END_IF
END_IF
CallRequest(IsExecute := FALSE);
ActiveBlock := 0;
FinishRequest := TRUE;
