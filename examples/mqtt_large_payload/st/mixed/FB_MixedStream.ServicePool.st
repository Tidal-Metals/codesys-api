// Action ServicePool: collect finished parts first (done, timeout, rejected), hand the next parts to idle
// publishers, and close the round when every part is finished. Called before the schedule check, so a round
// whose last part finished in this scan no longer counts as busy, and again right after a round starts.
// ---- implementation ----
FOR Index := 1 TO PoolInUse DO
	IF IsRoundActive AND NOT IsRequested[Index] AND NextPart < RoundParts THEN
		Pool[Index](send := FALSE);	// re-arm: the next send TRUE is a rising edge
		PoolOffset[Index] := PartStart[NextPart];
		PoolLength[Index] := PartLength[NextPart];
		NextPart := NextPart + 1;
		IsRequested[Index] := TRUE;
	END_IF
	Pool[Index](Topic := ADR(Topic), PublishAsString := FALSE, Payload := ADR(Data[PoolOffset[Index]]),
		PayloadLength := PoolLength[Index], QoSIn := PublishQoS, MRetain := FALSE, send := IsRequested[Index]);
	IF IsRequested[Index] AND (Pool[Index].done OR Pool[Index].SendTimeout OR Pool[Index].Rejected) THEN
		IF Pool[Index].done THEN
			PartsDone := PartsDone + 1;
		ELSE
			TimeoutCount := TimeoutCount + 1;
		END_IF
		IsRequested[Index] := FALSE;
		PartsFinished := PartsFinished + 1;
		// next part for this publisher in the same scan
		IF NextPart < RoundParts THEN
			Pool[Index](send := FALSE);
			PoolOffset[Index] := PartStart[NextPart];
			PoolLength[Index] := PartLength[NextPart];
			NextPart := NextPart + 1;
			IsRequested[Index] := TRUE;
			Pool[Index](Topic := ADR(Topic), PublishAsString := FALSE, Payload := ADR(Data[PoolOffset[Index]]),
				PayloadLength := PoolLength[Index], QoSIn := PublishQoS, MRetain := FALSE, send := TRUE);
		END_IF
	END_IF
END_FOR

IF IsRoundActive AND PartsFinished >= RoundParts THEN
	IsRoundActive := FALSE;
	LastSendUs := ULINT_TO_UDINT(NowUs() - RequestUs);
	LastSendScans := ScanCount - RequestScan;
	MaxSendUs := MAX(MaxSendUs, LastSendUs);
	MaxSendScans := MAX(MaxSendScans, LastSendScans);
	SumSendUs := SumSendUs + LastSendUs;
	SumSendScans := SumSendScans + LastSendScans;
	RoundsDone := RoundsDone + 1;
END_IF
