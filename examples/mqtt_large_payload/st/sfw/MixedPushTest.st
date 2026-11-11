PROGRAM MixedPushTest
// MixedTest's mixed-rate load through MQTT.MqttStoreForward (library 1.4.0.0) instead of MQTTPublish pools: the same
// two streams, messages and statistics (FB_MixedPushStream), each message handed to the block with Push. QoS 1 only.
// mixed_rate_test.py --push drives it. Called by PLC_PRG after StoreForwardTest, before the end-of-scan client call;
// PLC_PRG makes that call when IsLiveHandedOff, and CallClient keeps calling while IsSendInFlight, early stop on
// IsUnsentPending while IsEnabled (patch_demo_store_forward.py adds all three, in the MQTT 5 demo copy only).
// One block for both streams, as a comms program would have it: one buffer, one call per scan after both streams'
// pushes, one set of lanes and out slots, one live-first fence. Scan figures are PLC_PRG's of the scan before.
VAR CONSTANT
	LINE_BYTES : UDINT := 24;               // a "<tag>:<value>" line, worst case with margin (9-char name, measured mean 13-16 B)
	HEADER_BYTES : UDINT := 64;             // "MIX:..." header line, with room to spare
	MAX_SLOT_BYTES : UDINT := 32000;        // FB_MixedPushStream.MAX_BYTES: no part is larger than a round
END_VAR
VAR
	// Settings, written online
	IsEnabled : BOOL;                       // configures the block on the first enable
	SlowTagsPerMessage : UINT := 1500;
	FastTagsPerMessage : UINT := 500;
	SlowPeriod : TIME := T#1S;
	FastPeriod : TIME := T#100MS;
	ToleranceUs : ULINT := 20000;
	IsPushOffline : BOOL;                   // push while the broker is down (held); FALSE skips those periods, as MixedTest
	ResetStats : BOOL;
	// the block's configuration: on the first enable and on ConfigureRequest (with the block idle: Reset refuses while
	// a sample is in the client, and the configuration is then retried every scan while IsEnabled)
	LiveLanes : UINT := 2;
	BacklogLanes : UINT := 4;
	SlotTopicSize : UINT := 64;
	SlotPayloadSize : UDINT := 0;           // 0: from the larger TagsPerMessage, LINE_BYTES a tag + HEADER_BYTES (<= MAX_SLOT_BYTES)
	StorageBytes : UDINT := 262144;         // part of Storage given to Configure
	ConfigureRequest : BOOL;                // Reset(Discard) and Configure again with the settings above
	// the block's runtime inputs, passed every call
	BacklogStartsPerCall : UINT := 2;
	BacklogBytesPerCall : UDINT := 8192;
	ReservedOutSlots : UINT := 2;
	ReservedCredits : UINT := 2;
	IsHoldOnNoSubscribers : BOOL := TRUE;
	NoSubscriberPause : TIME := T#5S;

	Slow : FB_MixedPushStream;
	Fast : FB_MixedPushStream;
	Sfw : MQTT.MqttStoreForward;
	Storage : ARRAY[0..262143] OF BYTE;       // 256 KiB, keeps the application small (RealisticSfwTest has the big buffer)
	IsSendInFlight : BOOL;                  // PLC_PRG.CallClient keeps calling the client while this is TRUE
	IsLiveHandedOff : BOOL;                 // PLC_PRG makes the end-of-scan client call
	BlockNowMs : UDINT;                     // SysTimeGetMs() just before the block's call, for the streams' next scan
	SlotBytes : UDINT;
	StartUs : ULINT;

	// Results, read online
	ScanCount : UDINT;                      // scans while enabled
	SumCycleUs : ULINT;
	MaxCycleUs : UDINT;
	SumScanClientUs : ULINT;
	MaxScanClientUs : UDINT;
	MaxIntervalUs : UDINT;
	MinIntervalUs : UDINT := 16#FFFFFFFF;
	SumClientCalls : ULINT;
	IsCounting : BOOL;
	IsConfigured : BOOL;
	ConfigureCount : UDINT;
	ConfiguredSlotBytes : UDINT;
	LastConfigureError : MQTT.STORE_FORWARD_ERROR;
	Capacity : UINT;                        // slots
	// the block's counters since download (mixed_rate_test.py takes differences)
	PushedCount : ULINT;
	DeliveredCount : ULINT;
	DroppedCount : ULINT;
	RefusedCount : ULINT;
	DiscardedCount : ULINT;
	LiveDeferredCount : ULINT;
	NotAcceptedCount : ULINT;
	InvalidCount : ULINT;
	// the block's state after its call, and maxima since ResetStats
	QueuedCount : UINT;
	InFlightCount : UINT;
	HasWork : BOOL;
	MaxQueuedCount : UINT;
	MaxInFlightCount : UINT;
	MaxOldestAgeMs : UDINT;
	BlockUs : UDINT;                        // the block's call, every scan
	MaxBlockUs : UDINT;
	SumBlockUs : ULINT;                     // while IsEnabled (over ScanCount)
	LiveHandOffScans : UDINT;
END_VAR
// ---- implementation ----
IF ResetStats THEN
	ScanCount := 0; SumCycleUs := 0; MaxCycleUs := 0; SumScanClientUs := 0; MaxScanClientUs := 0;
	MaxIntervalUs := 0; MinIntervalUs := 16#FFFFFFFF; SumClientCalls := 0;
	MaxQueuedCount := 0; MaxInFlightCount := 0; MaxOldestAgeMs := 0; MaxBlockUs := 0; SumBlockUs := 0;
	LiveHandOffScans := 0;
END_IF
IF IsCounting THEN
	ScanCount := ScanCount + 1;
	SumCycleUs := SumCycleUs + PLC_PRG.CycleUs;
	MaxCycleUs := MAX(MaxCycleUs, PLC_PRG.CycleUs);
	SumScanClientUs := SumScanClientUs + PLC_PRG.ScanClientUs;
	MaxScanClientUs := MAX(MaxScanClientUs, PLC_PRG.ScanClientUs);
	MaxIntervalUs := MAX(MaxIntervalUs, PLC_PRG.IntervalUs);
	MinIntervalUs := MIN(MinIntervalUs, PLC_PRG.IntervalUs);
	SumClientCalls := SumClientCalls + INT_TO_ULINT(PLC_PRG.ClientCall);
END_IF
IsCounting := IsEnabled;

// Configure before the first push (after SetMqttInOut: Configure reads COM_CONFIG.CountSlotsOut)
IF ConfigureRequest OR (IsEnabled AND NOT IsConfigured) THEN
	ConfigureRequest := FALSE;
	SlotBytes := SlotPayloadSize;
	IF SlotBytes = 0 THEN
		SlotBytes := MIN(MAX_SLOT_BYTES,
			UINT_TO_UDINT(MAX(SlowTagsPerMessage, FastTagsPerMessage)) * LINE_BYTES + HEADER_BYTES);
	END_IF
	Sfw.Reset(Discard := TRUE);
	Sfw.SetMqttInOut(MQTT_IN_OUT := PLC_PRG.MqttLink);
	IsConfigured := Sfw.Configure(Storage := ADR(Storage), StorageSize := MIN(StorageBytes, SIZEOF(Storage)),
		SlotTopicSize := SlotTopicSize, SlotPayloadSize := SlotBytes, LiveLanes := LiveLanes,
		BacklogLanes := BacklogLanes);
	ConfigureCount := ConfigureCount + 1;
	ConfiguredSlotBytes := SlotBytes;
	LastConfigureError := Sfw.LastConfigureError;
END_IF

Slow(IsEnabled := IsEnabled, StreamId := 'S', FirstTag := 1, LastTag := 1500, TagsPerMessage := SlowTagsPerMessage,
	Period := SlowPeriod, Topic := 'raw_data_demo/mixed/slow', ToleranceUs := ToleranceUs,
	IsPushOffline := IsPushOffline, BlockNowMs := BlockNowMs, ResetStats := ResetStats, Sfw := Sfw);
Fast(IsEnabled := IsEnabled, StreamId := 'F', FirstTag := 1501, LastTag := 2000, TagsPerMessage := FastTagsPerMessage,
	Period := FastPeriod, Topic := 'raw_data_demo/mixed/fast', ToleranceUs := ToleranceUs,
	IsPushOffline := IsPushOffline, BlockNowMs := BlockNowMs, ResetStats := ResetStats, Sfw := Sfw);
ResetStats := FALSE;

// Once per scan, after both streams' pushes: this scan's samples to the client, then backlog if admitted
BlockNowMs := SysTimeCore.SysTimeGetMs();
StartUs := NowUs();
Sfw(AcceptPush := TRUE, Enable := TRUE, IsHoldOnNoSubscribers := IsHoldOnNoSubscribers,
	NoSubscriberPause := NoSubscriberPause, BacklogStartsPerCall := BacklogStartsPerCall,
	BacklogBytesPerCall := BacklogBytesPerCall, ReservedOutSlots := ReservedOutSlots, ReservedCredits := ReservedCredits,
	IsInferRefusals := FALSE);
BlockUs := ULINT_TO_UDINT(NowUs() - StartUs);
MaxBlockUs := MAX(MaxBlockUs, BlockUs);
IF IsEnabled THEN
	SumBlockUs := SumBlockUs + BlockUs;
END_IF

Capacity := Sfw.Capacity;
PushedCount := Sfw.PushedCount;
DeliveredCount := Sfw.DeliveredCount;
DroppedCount := Sfw.DroppedCount;
RefusedCount := Sfw.RefusedCount + Sfw.InferredRefusedCount;
DiscardedCount := Sfw.DiscardedCount;
LiveDeferredCount := Sfw.LiveDeferredCount;
NotAcceptedCount := Sfw.NotAcceptedCount;
InvalidCount := Sfw.InvalidCount;
QueuedCount := Sfw.QueuedCount;
InFlightCount := Sfw.InFlightCount;
HasWork := Sfw.HasWork;
MaxQueuedCount := MAX(MaxQueuedCount, QueuedCount);
MaxInFlightCount := MAX(MaxInFlightCount, InFlightCount);
MaxOldestAgeMs := MAX(MaxOldestAgeMs, Sfw.OldestAgeMs);
IsSendInFlight := Sfw.InFlightCount > 0;
IsLiveHandedOff := Sfw.IsLiveHandedOff;
IF IsLiveHandedOff THEN
	LiveHandOffScans := LiveHandOffScans + 1;
END_IF
