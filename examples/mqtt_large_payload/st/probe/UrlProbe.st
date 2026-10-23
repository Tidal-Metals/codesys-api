PROGRAM UrlProbe
// The library's broker URL parsing (MQTT.STRING_TO_URL, as MQTT_CONTROL uses it) on a string written online:
// url_test.py checks user, password, host and port for credentials with '@', ':' and long passwords.
VAR
	Input : STRING(250);                    // written online; empty = idle
	Parsed : MQTT.URL;
	User : STRING(128);
	Password : STRING(128);
	Domain : STRING(80);
	Port : WORD;
	ParseCount : UDINT;
	LastInput : STRING(250);
END_VAR
// ---- implementation ----
IF Input <> '' AND Input <> LastInput THEN
	LastInput := Input;
	Parsed := MQTT.STRING_TO_URL(STR := Input, DEFAULT_PROTOCOL := '', DEFAULT_PATH := '/');
	User := Parsed.USER;
	Password := Parsed.PASSWORD;
	Domain := Parsed.DOMAIN;
	Port := Parsed.PORT;
	ParseCount := ParseCount + 1;
END_IF
