METHOD StartNext : BOOL
// Starts the next request on this line, TRUE if it started one. Writes go first, so a changed setpoint never
// waits behind a round of reads. Reads go round-robin over the due blocks, so one device can't starve another.
VAR
	Index : INT;
	Candidate : INT;
	TagIndex : INT;
	RawValue : REAL;
END_VAR
// ---- implementation ----
FOR Index := 1 TO GVL_Bus.WRITE_COUNT DO
	TagIndex := GVL_Bus.Writes[Index].TagIndex;
	IF TagIndex > 0 AND GVL_Bus.Writes[Index].Line = LineIndex
			AND_THEN GVL_Tags.Tags[TagIndex].Quality = E_Quality.GOOD
			AND_THEN (NOT HasWritten[Index] OR GVL_Tags.Tags[TagIndex].Value <> WriteSentValue[Index] OR NowMs >= WriteDueMs[Index]) THEN
		WriteValue := GVL_Tags.Tags[TagIndex].Value;
		RawValue := (WriteValue - GVL_Tags.TagConfig[TagIndex].Offset) / GVL_Tags.TagConfig[TagIndex].Scale;
		// Range first, conversion after: REAL_TO_INT outside INT can fault.
		IF RawValue >= -32768.0 AND RawValue <= 32767.0 THEN
			WriteRaw := REAL_TO_INT(RawValue);
			ActiveWrite := Index;
			StartUs := F_NowUs();
			CallRequest(IsExecute := TRUE);
			StartNext := TRUE;
			RETURN;
		END_IF
		GVL_Bus.WriteErrors[Index] := GVL_Bus.WriteErrors[Index] + 1;
		HasWritten[Index] := TRUE;              // don't retry an unwritable value every call
		WriteSentValue[Index] := WriteValue;
		WriteDueMs[Index] := NowMs + GVL_Bus.Writes[Index].RefreshMs;
	END_IF
END_FOR

FOR Index := 0 TO GVL_Bus.BLOCK_COUNT - 1 DO
	Candidate := (NextBlock - 1 + Index) MOD GVL_Bus.BLOCK_COUNT + 1;
	IF GVL_Bus.Blocks[Candidate].Line = LineIndex AND NowMs >= BlockDueMs[Candidate] THEN
		ActiveBlock := Candidate;
		Block := GVL_Bus.Blocks[Candidate];
		NextBlock := Candidate MOD GVL_Bus.BLOCK_COUNT + 1;
		StartUs := F_NowUs();
		CallRequest(IsExecute := TRUE);
		StartNext := TRUE;
		RETURN;
	END_IF
END_FOR
