# to8-font-converter

This tools converts an Atari FNT File into a THOMSON compatible G0 font.

Atari FNT Files can be found here <https://github.com/TheRobotFactory/EightBit-Atari-Fonts>.

This offers a very large set of 8-bits font for THOMSON Computers.

## How to build & run this tool

### Building

```bash
$  mvn package
```

Then, executables were generated in target subfolder :
- to8-font-converter (for Linux and MacOS)
- to8-font-converter.exe (for Windows, obviously)
- to8-font-converter-0.0.1-SNAPSHOT-jar-with-dependencies.jar (Pure Java)

### Using

Generating a RAW binary file :

```bash
$ to8-font-converter -f ATARI-FONT.FNT -o THOMSON-G0-FONT.RAW
```

Generating a BIN file (with headers : implementation address and size. This example set the implementation address at `$7000`.

```bash
$ to8-font-converter -f ATARI-FONT.FNT -o THOMSON-G0-FONT.BIN -b --org 7000
```

Generating only few characters. This example generates only the caracters `Q`,`W`,`E`,`R`,`T`,`Y`,`0`,`1`. This is interesting if you want to take care of memory use. 

```bash
$ to8-font-converter -f ATARI-FONT.FNT -o THOMSON-G0-FONT.RAW --convert-only=QWERTY01
```

Warning: the chars are placed from the code $20 (space). In thi example `Q  is at $20`, `W  is at $21`, `E  is at $22`, etc.
This option is only working for the RAW file generation only, up to now.


### Using in THOMSON

- LOAD the RAW file at a specified address, for example $6500 (with LOADM or custom disk operation)

- Then change PTGENE pointer : 

```
LDX #$6500   * target address of the new font
STX $60CF    * store this address at PTGENE :  $60CF
```

