METHOD Take : BOOL
// One server: decode its image into GVL_Bus.Raw once it has been error-free for HOLD_MS; unhealthy until then.
VAR_INPUT
	Number : INT;                       // position in WasError / ErrorEdges
	Block : INT;                        // its GVL_Bus.Blocks row (the decode description)
	IsError : BOOL;                     // the server's xError
END_VAR
VAR_IN_OUT
	Image : ARRAY[0..5] OF WORD;
END_VAR
VAR
	Source : INT;
	Index : INT;
END_VAR
// ---- implementation ----
Source := GVL_Bus.Blocks[Block].Source;
IF IsError AND NOT WasError[Number] THEN
	ErrorEdges[Number] := ErrorEdges[Number] + 1;
END_IF
WasError[Number] := IsError;
IF IsError THEN
	ErrorCycles[Number] := ErrorCycles[Number] + 1;
	LastErrorMs[Number] := NowMs;
END_IF
GVL_Bus.SourceWriting[Source] := TRUE;
IF LastErrorMs[Number] <> 0 AND NowMs - LastErrorMs[Number] < HOLD_MS THEN
	GVL_Bus.SourceHealthy[Source] := FALSE;
ELSE
	FOR Index := 0 TO 5 DO
		Words[Index] := Image[Index];
	END_FOR
	F_BusDecode(FirstEntry := GVL_Bus.Blocks[Block].FirstEntry, EntryCount := GVL_Bus.Blocks[Block].EntryCount,
		Words := Words, Bits := Bits);
	GVL_Bus.SourceHealthy[Source] := TRUE;
	GVL_Bus.SourceLastGoodMs[Source] := NowMs;
END_IF
GVL_Bus.SourceWriting[Source] := FALSE;
Take := TRUE;
