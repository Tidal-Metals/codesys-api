METHOD PublishReceived : BOOL
VAR_INPUT
	Data : MQTT.CALLBACK_DATA;
END_VAR
VAR
	Index : UDINT;
	SumA : UDINT;
	SumB : UDINT;
	pByte : POINTER TO BYTE;
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
ReceivedCount := ReceivedCount + 1;
PublishReceived := TRUE;
