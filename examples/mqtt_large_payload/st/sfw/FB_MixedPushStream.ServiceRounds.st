// Action ServiceRounds: close the rounds whose every part has left the block (PUBACK, refusal, drop or discard), oldest
// first. The block keeps no per-sample receipt, so a round is closed once the block holds nothing pushed before or with
// it: nothing held at all, or the oldest sample held (by push order) was pushed after the round's last Push. That push
// time is BlockNowMs - OldestAgeMs from the block's call in the previous scan; BlockNowMs is taken just before that call,
// so the estimate errs late, never early. Millisecond resolution: a sample of the other stream pushed in the same
// millisecond holds the round until it leaves too. Called first in every scan, never right after a push (the block's
// outputs are fresh only after its own call, which comes after both streams' pushes).
// ---- implementation ----
ServiceNowUs := NowUs();
WHILE TrackCount > 0 AND_THEN (NOT Sfw.HasWork
		OR_ELSE UDINT_TO_DINT(BlockNowMs - Sfw.OldestAgeMs - TrackPushMs[TrackHead]) > 0) DO
	LastSendUs := ULINT_TO_UDINT(ServiceNowUs - TrackRequestUs[TrackHead]);
	LastSendScans := ScanCount - TrackScan[TrackHead];
	MaxSendUs := MAX(MaxSendUs, LastSendUs);
	MaxSendScans := MAX(MaxSendScans, LastSendScans);
	SumSendUs := SumSendUs + LastSendUs;
	SumSendScans := SumSendScans + LastSendScans;
	PartsDone := PartsDone + UINT_TO_UDINT(TrackParts[TrackHead]);
	RoundsDone := RoundsDone + 1;
	TrackHead := (TrackHead + 1) MOD MAX_TRACKED;
	TrackCount := TrackCount - 1;
END_WHILE
IsRoundActive := TrackCount > 0;
