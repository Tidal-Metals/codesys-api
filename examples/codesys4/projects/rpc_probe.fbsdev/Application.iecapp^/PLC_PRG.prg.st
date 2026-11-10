PROGRAM PLC_PRG
VAR
    counter : INT;
    flag : BOOL;
END_VAR
counter := counter + 1;
flag := counter > 10;
END_PROGRAM
