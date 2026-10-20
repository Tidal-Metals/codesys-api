PROGRAM PRG_SimInputs
// Bench stand-in for local I/O: the tags of source 0 keep moving. Each scan ChangePerScan of them get a new raw
// value, cycling through the table (100 per 50 ms scan = every tag changes about once a second). Tags of the bus
// devices come from PRG_Bus instead. Values stay inside the generated ranges: BOOL 0/1, INT 0..99,999, REAL raw
// 0..4,999 (scale 0.1 -> 0..499.9).
VAR
	ChangePerScan : INT := 100;
	NextIndex : INT := 1;
	Step : DINT;
	Count : INT;
END_VAR
// ---- implementation ----
Step := Step + 1;
FOR Count := 1 TO ChangePerScan DO
	IF GVL_Tags.TagConfig[NextIndex].Source = 0 THEN
		CASE GVL_Tags.TagConfig[NextIndex].Kind OF
			E_TagKind.BOOL_TAG:
				GVL_Tags.RawInputs[NextIndex] := DINT_TO_REAL((Step + NextIndex) MOD 2);
			E_TagKind.INT_TAG:
				GVL_Tags.RawInputs[NextIndex] := DINT_TO_REAL((Step * 7 + NextIndex) MOD 100000);
		ELSE
			GVL_Tags.RawInputs[NextIndex] := DINT_TO_REAL((Step * 13 + NextIndex * 3) MOD 5000);
		END_CASE
	END_IF
	NextIndex := NextIndex MOD GVL_Tags.TAG_COUNT + 1;
END_FOR
