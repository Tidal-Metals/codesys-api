// Action EvaluateAlarms (step 4). One alarm shown; in the full design alarms are rows in a generated
// table (tag, setpoint tag, direction, hysteresis, delay, priority) evaluated in a loop.
// ---- implementation ----
// HH alarm with hysteresis. A value or a setpoint that can't be trusted counts as an alarm (fail safe).
IF GVL_Tags.Tags[GVL_Tags.TAG_AIT_1508].Quality <> E_Quality.GOOD
		OR GVL_Tags.Tags[GVL_Tags.TAG_AIT_1508_HH_SP].Quality <> E_Quality.GOOD THEN
	AIT_1508_HH := TRUE;
ELSIF GVL_Tags.Tags[GVL_Tags.TAG_AIT_1508].Value >= GVL_Tags.Tags[GVL_Tags.TAG_AIT_1508_HH_SP].Value THEN
	AIT_1508_HH := TRUE;
ELSIF GVL_Tags.Tags[GVL_Tags.TAG_AIT_1508].Value
		< GVL_Tags.Tags[GVL_Tags.TAG_AIT_1508_HH_SP].Value - ALARM_HYSTERESIS THEN
	AIT_1508_HH := FALSE;
END_IF

// A remote E-stop is active unless it is positively reported clear: an untrusted signal, or one that has
// stopped arriving, counts as a stop. NOT (< 0.5) also treats NaN as a stop.
LSS_E_STOP_ACTIVE := NOT (GVL_Tags.Tags[GVL_Tags.TAG_LSS_E_STOP].Value < 0.5)
	OR GVL_Tags.Tags[GVL_Tags.TAG_LSS_E_STOP].Quality <> E_Quality.GOOD;
