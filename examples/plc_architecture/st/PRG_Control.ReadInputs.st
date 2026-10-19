// Action ReadInputs (step 1): raw values and the quality of their source. A failed or silent source keeps
// its last good raw value, marked, instead of whatever the I/O image holds. Requests and setpoints are not
// inputs: they only change through ApplyCommands.
// ---- implementation ----
FOR Index := 1 TO GVL_Tags.TAG_COUNT DO
	IF NOT GVL_Tags.TagConfig[Index].IsWritable THEN
		IF NOT GVL_Tags.SourceIsHealthy[GVL_Tags.TagConfig[Index].Source] THEN
			GVL_Tags.Tags[Index].SourceQuality := E_Quality.COMM_FAIL;       // local I/O diagnostics too
		ELSIF GVL_Tags.TagConfig[Index].Source = 0 THEN
			GVL_Tags.Tags[Index].Raw := GVL_Tags.RawInputs[Index];
			GVL_Tags.Tags[Index].SourceQuality := E_Quality.GOOD;
			GVL_Tags.Tags[Index].UpdatedAtMs := NowAtMs;
		ELSIF GVL_Tags.SourceUpdatedAtMs[GVL_Tags.TagConfig[Index].Source] = 0 THEN
			GVL_Tags.Tags[Index].SourceQuality := E_Quality.INIT;            // no sample since start-up
		ELSIF GVL_Tags.SourceUpdatedAtMs[GVL_Tags.TagConfig[Index].Source] < NowAtMs
				AND NowAtMs - GVL_Tags.SourceUpdatedAtMs[GVL_Tags.TagConfig[Index].Source]
					> TIME_TO_ULINT(GVL_Tags.TagConfig[Index].StaleAfter) THEN
			GVL_Tags.Tags[Index].SourceQuality := E_Quality.STALE;
		ELSE
			GVL_Tags.Tags[Index].Raw := GVL_Tags.RawInputs[Index];
			GVL_Tags.Tags[Index].SourceQuality := E_Quality.GOOD;
			GVL_Tags.Tags[Index].UpdatedAtMs := GVL_Tags.SourceUpdatedAtMs[GVL_Tags.TagConfig[Index].Source];
		END_IF
	END_IF
END_FOR
