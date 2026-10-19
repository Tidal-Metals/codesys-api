// Action DetectChanges: report-by-exception check over all tags. A BOOL or DINT counts as changed
// when it differs from the last value sent, a REAL when it moved more than RealDeadband. The last-sent
// copy is updated for changed tags, as it would be once they are in the message.
// ---- implementation ----
ChangedBools := 0;
ChangedInts := 0;
ChangedReals := 0;
FOR Index := 1 TO BOOL_COUNT DO
	IF Bools[Index] <> LastBools[Index] THEN
		LastBools[Index] := Bools[Index];
		ChangedBools := ChangedBools + 1;
	END_IF
END_FOR
FOR Index := 1 TO INT_COUNT DO
	IF Ints[Index] <> LastInts[Index] THEN
		LastInts[Index] := Ints[Index];
		ChangedInts := ChangedInts + 1;
	END_IF
END_FOR
FOR Index := 1 TO REAL_COUNT DO
	IF ABS(Reals[Index] - LastReals[Index]) > RealDeadband THEN
		LastReals[Index] := Reals[Index];
		ChangedReals := ChangedReals + 1;
	END_IF
END_FOR
