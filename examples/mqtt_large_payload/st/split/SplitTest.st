PROGRAM SplitTest
// The same data as one large message or many small ones: every Period, TotalBytes go out as Parts messages
// on Topic through Publishers MQTTPublish instances (one message in flight each). split_test.py drives it.
// Part p (0-based) is Data[Offset .. Offset + Length - 1], Offset = p * (TotalBytes / Parts) + MIN(p, rest);
// it starts with 16 ASCII digits "RRRRRRPPPPPKKKKK" (round, part, parts), then Data's pattern byte
// (Offset * 31 + 7) MOD 251, so the broker-side checker verifies every byte of every part.
// A publisher whose message is done is re-armed (called with send FALSE) and given the next part in the same
// scan: the fastest an application can feed MQTTPublish, whose send input is edge-triggered.
VAR CONSTANT
	MAX_BYTES : UDINT := 40000;
	MAX_PUBLISHERS : UINT := 32;
	HEADER_BYTES : UDINT := 16;
END_VAR
VAR
	// Settings, written online
	IsEnabled : BOOL;
	TotalBytes : UDINT := 26000;
	Parts : UDINT := 1;                     // each part at least HEADER_BYTES long
	Publishers : UINT := 8;                 // 1 .. MAX_PUBLISHERS
	QoSLevel : BYTE;                        // 0, 1 or 2
	Period : TIME := T#1S;                  // a new round this long after the previous one finished
	Topic : STRING(64) := 'raw_data_demo/split';
	ResetStats : BOOL;

	// Results, read online (microseconds unless named *Scans/*Count)
	Round : UDINT;                          // rounds started
	RoundsDone : UDINT;
	LastRoundUs : UDINT;                    // first part requested -> last part done
	MaxRoundUs : UDINT;
	SumRoundUs : ULINT;
	LastRoundScans : UDINT;
	MaxRoundScans : UDINT;
	SumRoundScans : UDINT;
	MaxScanClientUs : UDINT;                // the most client time in one scan while a round was going
	PartsDone : UDINT;                      // all rounds
	TimeoutCount : UDINT;                   // parts given up (SendTimeout, or Rejected by the broker)
	IsRoundActive : BOOL;

	// State
	Pool : ARRAY[1..MAX_PUBLISHERS] OF MQTT.MQTTPublish;
	IsRequested : ARRAY[1..MAX_PUBLISHERS] OF BOOL;
	IsReady : BOOL;
	Data : ARRAY[0..MAX_BYTES - 1] OF BYTE;
	PatternBytes : UDINT;                   // Data holds the pattern up to here ...
	PatternParts : UDINT;                   // ... with the headers of a round of this many parts
	PartOffset : ARRAY[1..MAX_PUBLISHERS] OF UDINT;
	PartLength : ARRAY[1..MAX_PUBLISHERS] OF UDINT;
	NextPart : UDINT;                       // 0-based
	RoundParts : UDINT;                     // parts finished in this round
	RoundTotal : UDINT;                     // settings latched for the round
	RoundCount : UDINT;
	RoundPublishers : UINT;
	PublishQoS : MQTT.QoS;
	BaseLength : UDINT;
	Rest : UDINT;
	RoundStartUs : ULINT;
	RoundStartScan : UDINT;
	ScanCount : UDINT;
	IsClientTimeCounted : BOOL;             // count PLC_PRG.ScanClientUs of the scan before (lags one scan)
	Timer : TON;
	Index : UINT;
	Position : UDINT;
	Number : UDINT;
END_VAR
// ---- implementation ----
ScanCount := ScanCount + 1;
IF NOT IsReady THEN
	IsReady := TRUE;
	FOR Index := 1 TO MAX_PUBLISHERS DO
		Pool[Index].SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
	END_FOR
END_IF
IF ResetStats THEN
	ResetStats := FALSE;
	RoundsDone := 0; MaxRoundUs := 0; SumRoundUs := 0; MaxRoundScans := 0; SumRoundScans := 0;
	MaxScanClientUs := 0; PartsDone := 0; TimeoutCount := 0; LastRoundUs := 0; LastRoundScans := 0;
END_IF
IF IsClientTimeCounted THEN
	MaxScanClientUs := MAX(MaxScanClientUs, PLC_PRG.ScanClientUs);
END_IF
IsClientTimeCounted := IsRoundActive;

// Start a round: latch the settings, write each part's header into Data
Timer(IN := IsEnabled AND NOT IsRoundActive AND PLC_PRG.IsBrokerConnected, PT := Period);
IF Timer.Q AND TotalBytes >= HEADER_BYTES AND TotalBytes <= MAX_BYTES AND Parts >= 1
	AND Parts <= TotalBytes / HEADER_BYTES AND Publishers >= 1 AND Publishers <= MAX_PUBLISHERS THEN
	Timer(IN := FALSE);
	RoundTotal := TotalBytes;
	RoundCount := Parts;
	RoundPublishers := Publishers;
	CASE QoSLevel OF
		1: PublishQoS := MQTT.QoS.AtLeastOnce;
		2: PublishQoS := MQTT.QoS.ExactlyOnce;
	ELSE
		PublishQoS := MQTT.QoS.AtMostOnce;
	END_CASE
	// a new split: earlier headers sit at other offsets, so restore the whole pattern (outside the timed round)
	IF PatternBytes < RoundTotal OR PatternParts <> RoundCount THEN
		FOR Position := 0 TO RoundTotal - 1 DO
			Data[Position] := UDINT_TO_BYTE((Position * 31 + 7) MOD 251);
		END_FOR
		PatternBytes := RoundTotal;
		PatternParts := RoundCount;
	END_IF
	Round := Round + 1;
	BaseLength := RoundTotal / RoundCount;
	Rest := RoundTotal MOD RoundCount;
	FOR Number := 0 TO RoundCount - 1 DO
		Position := Number * BaseLength + MIN(Number, Rest);
		WriteDigits(pDest := ADR(Data[Position]), Value := Round, Digits := 6);
		WriteDigits(pDest := ADR(Data[Position + 6]), Value := Number, Digits := 5);
		WriteDigits(pDest := ADR(Data[Position + 11]), Value := RoundCount, Digits := 5);
	END_FOR
	NextPart := 0;
	RoundParts := 0;
	RoundStartUs := NowUs();
	RoundStartScan := ScanCount;
	IsRoundActive := TRUE;
	IsClientTimeCounted := TRUE;
END_IF

// Feed the publishers
FOR Index := 1 TO MAX_PUBLISHERS DO
	IF IsRoundActive AND Index <= RoundPublishers AND NOT IsRequested[Index] AND NextPart < RoundCount THEN
		Pool[Index](send := FALSE);	// re-arm: the next send TRUE is a rising edge
		PartOffset[Index] := NextPart * BaseLength + MIN(NextPart, Rest);
		PartLength[Index] := BaseLength + BOOL_TO_UDINT(NextPart < Rest);
		NextPart := NextPart + 1;
		IsRequested[Index] := TRUE;
	END_IF
	Pool[Index](Topic := ADR(Topic), PublishAsString := FALSE, Payload := ADR(Data[PartOffset[Index]]),
		PayloadLength := PartLength[Index], QoSIn := PublishQoS, MRetain := FALSE, send := IsRequested[Index]);
	IF IsRequested[Index] AND (Pool[Index].done OR Pool[Index].SendTimeout OR Pool[Index].Rejected) THEN
		IF Pool[Index].SendTimeout OR Pool[Index].Rejected THEN
			TimeoutCount := TimeoutCount + 1;
		ELSE
			PartsDone := PartsDone + 1;
		END_IF
		IsRequested[Index] := FALSE;
		RoundParts := RoundParts + 1;
		// next part for this publisher in the same scan
		IF NextPart < RoundCount THEN
			Pool[Index](send := FALSE);
			PartOffset[Index] := NextPart * BaseLength + MIN(NextPart, Rest);
			PartLength[Index] := BaseLength + BOOL_TO_UDINT(NextPart < Rest);
			NextPart := NextPart + 1;
			IsRequested[Index] := TRUE;
			Pool[Index](Topic := ADR(Topic), PublishAsString := FALSE, Payload := ADR(Data[PartOffset[Index]]),
				PayloadLength := PartLength[Index], QoSIn := PublishQoS, MRetain := FALSE, send := TRUE);
		END_IF
	END_IF
END_FOR

IF IsRoundActive AND RoundParts >= RoundCount THEN
	IsRoundActive := FALSE;
	LastRoundUs := ULINT_TO_UDINT(NowUs() - RoundStartUs);
	LastRoundScans := ScanCount - RoundStartScan;
	MaxRoundUs := MAX(MaxRoundUs, LastRoundUs);
	MaxRoundScans := MAX(MaxRoundScans, LastRoundScans);
	SumRoundUs := SumRoundUs + LastRoundUs;
	SumRoundScans := SumRoundScans + LastRoundScans;
	RoundsDone := RoundsDone + 1;
END_IF
