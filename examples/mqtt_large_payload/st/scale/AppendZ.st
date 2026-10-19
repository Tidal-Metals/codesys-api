FUNCTION AppendZ : BOOL
// Appends the zero-terminated text at pText to the buffer without copying it into a STRING input
// first (AppendText's STRING(255) input costs a string copy per call). All or nothing: on overflow
// the buffer is left as it was and FALSE is returned.
VAR_INPUT
	pBuffer : POINTER TO BYTE;          // ADR() of the destination STRING
	Capacity : UDINT;                   // SIZEOF() of the destination, terminator included
	pText : POINTER TO BYTE;            // ADR() of the text: a STRING variable or a literal
END_VAR
VAR_IN_OUT
	Used : UDINT;                       // current length of the destination, kept by the caller
END_VAR
VAR
	Start : UDINT;
	Index : UDINT;
END_VAR
// ---- implementation ----
Start := Used;
WHILE pText[Index] <> 0 DO
	IF Used + 1 >= Capacity THEN
		Used := Start;
		pBuffer[Start] := 0;
		AppendZ := FALSE;
		RETURN;
	END_IF
	pBuffer[Used] := pText[Index];
	Used := Used + 1;
	Index := Index + 1;
END_WHILE
pBuffer[Used] := 0;
AppendZ := TRUE;
