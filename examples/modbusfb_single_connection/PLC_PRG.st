PROGRAM PLC_PRG
VAR
    Poller : FB_ModbusTenUnits;
    AllTenValuesMatch : BOOL;
    i : INT;
END_VAR

Poller();
AllTenValuesMatch := Poller.xAllDevicesHealthy
    AND (Poller.aRegisters[1,0] = 1234) AND (Poller.aRegisters[1,1] = 5678)
    AND (Poller.aRegisters[2,0] = 2222) AND (Poller.aRegisters[2,1] = 3333);
FOR i := 3 TO 10 DO
    AllTenValuesMatch := AllTenValuesMatch
        AND (Poller.aRegisters[i,0] = (i * 100 + 1))
        AND (Poller.aRegisters[i,1] = (i * 100 + 2));
END_FOR;
END_PROGRAM
