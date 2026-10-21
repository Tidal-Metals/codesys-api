METHOD PublishReceived : BOOL
VAR_INPUT
	Data : MQTT.CALLBACK_DATA;
END_VAR
VAR
	Index : UDINT;
	SumA : UDINT;
	SumB : UDINT;
	pByte : POINTER TO BYTE;
	Sequence : UDINT;
	IsSequenced : BOOL;
END_VAR
// ---- implementation ----
// Adler-32 (as zlib.adler32) over the binary payload; the library reuses its buffer after this call.
SumA := 1;
SumB := 0;
pByte := Data.Payload;
IF Data.PayloadSize > 0 AND pByte <> 0 THEN
	FOR Index := 0 TO Data.PayloadSize - 1 DO
		SumA := (SumA + pByte[Index]) MOD 65521;
		SumB := (SumB + SumA) MOD 65521;
	END_FOR
END_IF
LastSize := Data.PayloadSize;
LastAdler32 := SumB * 65536 + SumA;

// Sequence check: 8 leading ASCII digits
IsSequenced := Data.PayloadSize >= 8 AND pByte <> 0;
Sequence := 0;
IF IsSequenced THEN
	FOR Index := 0 TO 7 DO
		IF pByte[Index] < 48 OR pByte[Index] > 57 THEN
			IsSequenced := FALSE;
		ELSE
			Sequence := Sequence * 10 + (pByte[Index] - 48);
		END_IF
	END_FOR
END_IF
IF IsSequenced THEN
	IF ResetSequence THEN
		ResetSequence := FALSE;
		LastSequence := 0;
		InOrderCount := 0;
		DuplicateCount := 0;
		GapCount := 0;
	END_IF
	IF Sequence = LastSequence + 1 THEN
		InOrderCount := InOrderCount + 1;
	ELSIF Sequence <= LastSequence THEN
		DuplicateCount := DuplicateCount + 1;
	ELSE
		GapCount := GapCount + (Sequence - LastSequence - 1);
		InOrderCount := InOrderCount + 1;
	END_IF
	IF Sequence > LastSequence THEN
		LastSequence := Sequence;
	END_IF
END_IF
ReceivedCount := ReceivedCount + 1;
PublishReceived := TRUE;
