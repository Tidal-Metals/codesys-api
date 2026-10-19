FUNCTION F_IsNumberText : BOOL
// TRUE for a plain decimal number of 1..MaxLength characters: an optional leading '-', digits, at most one
// '.'. With IsDigitsOnly, only unsigned integers (ids, timestamps). MaxLength keeps the value inside the
// target type (9 digits for a UDINT id, 15 for a millisecond timestamp). Run this before STRING_TO_REAL/
// _UDINT/_ULINT, which return 0 for text they can't read.
VAR_INPUT
	Text : STRING(40);
	IsDigitsOnly : BOOL;
	MaxLength : INT;
END_VAR
VAR
	pChar : POINTER TO BYTE;
	Length : INT;
	Index : INT;
	Digits : INT;
	Dots : INT;
END_VAR
// ---- implementation ----
F_IsNumberText := FALSE;
Length := LEN(Text);
IF Length < 1 OR Length > MaxLength THEN
	RETURN;
END_IF
pChar := ADR(Text);
FOR Index := 0 TO Length - 1 DO
	IF pChar[Index] >= 16#30 AND pChar[Index] <= 16#39 THEN
		Digits := Digits + 1;
	ELSIF pChar[Index] = 16#2E AND NOT IsDigitsOnly THEN
		Dots := Dots + 1;
	ELSIF NOT (pChar[Index] = 16#2D AND Index = 0 AND NOT IsDigitsOnly) THEN
		RETURN;                         // any other character, or '-' anywhere but first
	END_IF
END_FOR
F_IsNumberText := Digits > 0 AND Dots <= 1;
