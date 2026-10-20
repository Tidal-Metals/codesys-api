// Action CollectBusInputs (start of step 1): device values and health from the bus task. A source the bus task
// was updating when this scan started (SourceWriting) keeps last scan's values; it is complete next scan.
// ---- implementation ----
FOR Index := 1 TO GVL_Tags.SOURCE_COUNT DO
	IF GVL_Bus.IsBusSource[Index] AND NOT GVL_Bus.SourceWriting[Index] THEN
		GVL_Tags.SourceIsHealthy[Index] := GVL_Bus.SourceHealthy[Index];
		GVL_Tags.SourceUpdatedAtMs[Index] := GVL_Bus.SourceLastGoodMs[Index];
	END_IF
END_FOR
FOR Index := 1 TO GVL_Tags.TAG_COUNT DO
	Slot := GVL_Tags.TagConfig[Index].Source;
	IF GVL_Bus.IsBusSource[Slot] AND NOT GVL_Bus.SourceWriting[Slot] THEN
		GVL_Tags.RawInputs[Index] := GVL_Bus.Raw[Index];
	END_IF
END_FOR
