# to8-font-converter

This tools converts an Atari FNT File into a THOMSON compatible G0 font.

## How to build & run this tool

### Building

```bash
$  mvn compile assembly:single
```

Then, the generated executable JAR is in target subfolder.

### Using

```bash
$ java -jar ./target/to8-font-converter-0.0.1-SNAPSHOT-jar-with-dependencies.jar -f ATARI-FONT.FNT -o THOMSON.RAW
```

### Using in THOMSON

- LOAD the RAW file at a specified address, for example $6500
- Then change PTGENE pointer : 

```asm
	LDX #$6500   * target address of the new font
        STX $60CF    * store this address at PTGENE :  $60CF
```

