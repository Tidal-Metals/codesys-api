// Action EvaluatePermissives (step 5): what may run, from alarms only. A bypass is time-limited, needs the
// local key switch, and never overrides an E-stop.
// ---- implementation ----
IsBypassActive := LocalBypassEnable AND BypassUntilMs > NowAtMs;

P_1502_Permit := NOT LSS_E_STOP_ACTIVE
	AND (IsBypassActive OR NOT AIT_1508_HH);
