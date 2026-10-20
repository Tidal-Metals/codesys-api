PROGRAM PRG_SimInputs
// Bench stand-in for the I/O and bus adapters: every source healthy and fresh, and inputs that keep moving.
// Each scan ChangePerScan tags get a new raw value, cycling through the table (100 per 50 ms scan = every tag
// changes once a second). Values stay inside the generated ranges: BOOL 0/1, INT 0..99,999, REAL raw
// 0..4,999 (scale 0.1 -> 0..499.9).
VAR
	ChangePerScan : INT := 100;
	NextIndex : INT := 1;
	Step : DINT;
	Index : INT;
	Count : INT;
	NowAtMs : ULINT;
END_VAR
// ---- implementation ----
NowAtMs := F_NowMs();
FOR Index := 1 TO GVL_Tags.SOURCE_COUNT DO
	GVL_Tags.SourceIsHealthy[Index] := TRUE;
	GVL_Tags.SourceUpdatedAtMs[Index] := NowAtMs;
END_FOR
Step := Step + 1;
FOR Count := 1 TO ChangePerScan DO
	CASE GVL_Tags.TagConfig[NextIndex].Kind OF
		E_TagKind.BOOL_TAG:
			GVL_Tags.RawInputs[NextIndex] := DINT_TO_REAL((Step + NextIndex) MOD 2);
		E_TagKind.INT_TAG:
			GVL_Tags.RawInputs[NextIndex] := DINT_TO_REAL((Step * 7 + NextIndex) MOD 100000);
	ELSE
		GVL_Tags.RawInputs[NextIndex] := DINT_TO_REAL((Step * 13 + NextIndex * 3) MOD 5000);
	END_CASE
	NextIndex := NextIndex MOD GVL_Tags.TAG_COUNT + 1;
END_FOR
