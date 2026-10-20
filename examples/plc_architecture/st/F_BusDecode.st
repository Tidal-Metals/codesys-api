FUNCTION F_BusDecode : BOOL
// Turns one block's reply into GVL_Bus.Raw for each of its entries. Call it with the source's SourceWriting
// flag set. A sentinel ("no reading") becomes NaN, so the tag goes INVALID in ComputeValues. Independent of
// the transport: FB_BusLine passes a ModbusFB reply, a native device-tree channel its mapped input image.
VAR_INPUT
	FirstEntry : INT;
	EntryCount : INT;
END_VAR
VAR_IN_OUT
	Words : ARRAY[0..124] OF WORD;      // register reply, first register at index 0
	Bits : ARRAY[0..1999] OF BYTE;      // bit reply, one byte per bit
END_VAR
VAR
	Index : INT;
	Entry : ST_BusEntry;
	RawInt : DINT;
	Raw32 : DWORD;
	Value : REAL;
	pReal : POINTER TO REAL;
	NanBits : DWORD := 16#7FC00000;
END_VAR
// ---- implementation ----
FOR Index := FirstEntry TO FirstEntry + EntryCount - 1 DO
	Entry := GVL_Bus.Entries[Index];
	IF Entry.Format = E_BusFormat.SINGLE_BIT THEN
		RawInt := SEL(Bits[Entry.Offset] <> 0, 0, 1);   // ModbusFB unpacks bit replies: one byte per coil (bench, 2026-10-20)
		Value := DINT_TO_REAL(RawInt);
	ELSIF Entry.Format = E_BusFormat.INT16 THEN
		RawInt := INT_TO_DINT(WORD_TO_INT(Words[Entry.Offset]));
		Value := DINT_TO_REAL(RawInt);
	ELSIF Entry.Format = E_BusFormat.UINT16 THEN
		RawInt := WORD_TO_DINT(Words[Entry.Offset]);
		Value := DINT_TO_REAL(RawInt);
	ELSE
		IF Entry.IsWordSwapped THEN
			Raw32 := SHL(WORD_TO_DWORD(Words[Entry.Offset + 1]), 16) OR WORD_TO_DWORD(Words[Entry.Offset]);
		ELSE
			Raw32 := SHL(WORD_TO_DWORD(Words[Entry.Offset]), 16) OR WORD_TO_DWORD(Words[Entry.Offset + 1]);
		END_IF
		RawInt := DWORD_TO_DINT(Raw32);
		IF Entry.Format = E_BusFormat.FLOAT32 THEN
			pReal := ADR(Raw32);
			Value := pReal^;
		ELSIF Entry.Format = E_BusFormat.UINT32 THEN
			Value := UDINT_TO_REAL(DWORD_TO_UDINT(Raw32));
		ELSE
			Value := DINT_TO_REAL(RawInt);
		END_IF
	END_IF
	IF Entry.HasSentinel AND RawInt = Entry.Sentinel THEN
		pReal := ADR(NanBits);
		Value := pReal^;
	END_IF
	GVL_Bus.Raw[Entry.TagIndex] := Value;
END_FOR
F_BusDecode := TRUE;
