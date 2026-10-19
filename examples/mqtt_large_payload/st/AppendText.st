FUNCTION AppendText : BOOL
// Appends Text to a long STRING without CONCAT, which stops at 255 characters.
// Returns FALSE and leaves the buffer unchanged when Text would not fit.
VAR_INPUT
	pBuffer : POINTER TO BYTE;  // ADR() of the destination STRING
	Capacity : UDINT;           // SIZEOF() of the destination, terminator included
	Text : STRING(255);         // one short piece; only the total may exceed 255
END_VAR
VAR_IN_OUT
	Used : UDINT;               // current length of the destination, kept by the caller
END_VAR
VAR
	pText : POINTER TO BYTE;
	TextLength : UDINT;
	Index : UDINT;
END_VAR
// ---- implementation ----
TextLength := INT_TO_UDINT(LEN(Text));
IF pBuffer = 0 OR Used + TextLength + 1 > Capacity THEN
	AppendText := FALSE;
	RETURN;
END_IF

pText := ADR(Text);
FOR Index := 1 TO TextLength DO
	pBuffer[Used] := pText[Index - 1];
	Used := Used + 1;
END_FOR
pBuffer[Used] := 0;
AppendText := TRUE;
