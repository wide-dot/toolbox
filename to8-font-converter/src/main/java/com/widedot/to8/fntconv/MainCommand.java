package com.widedot.to8.fntconv;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

import org.apache.commons.codec.DecoderException;
import org.apache.commons.codec.binary.Hex;
import org.apache.commons.lang3.ArrayUtils;
import org.apache.commons.lang3.StringUtils;

import lombok.extern.slf4j.Slf4j;
import picocli.CommandLine;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

@Command(name = "fnt-converter", description = "build a bootsector for TO8")
@Slf4j
public class MainCommand implements Runnable
{

	@Option(names = { "-f", "--fnt" }, paramLabel = "Input ATARI FNT File", description = "the FNT file")
	File fntFIle;

	@Option(names = { "-o", "--output" }, paramLabel = "Destination File", description = "Font File for Thomson")
	File destFile;
	
	@Option(names = { "-b", "--binary" }, paramLabel = "Binary File ?", description = "Produce a THOMSON BIN Format, compatible with LOADM")
	boolean isBinFormat;
	
	@Option(names = { "--org" }, paramLabel = "Org IMPL", description = "ORG address for the BIN generation")
	String orgAddress;
	
	@Option(names = { "--convert-only" }, paramLabel = "Char list", description = "Char list to convert")
	String convertedChars;

	public static void main(String[] args)
	{
		CommandLine cmdLine = new CommandLine(new MainCommand());
		if (args.length < 1)
		{
			cmdLine.execute("--help");
		}
		else
		{
			cmdLine.execute(args);
		}
	}

	@Override
	public void run()
	{
		
		
		try (InputStream in = new FileInputStream(fntFIle); OutputStream out = new FileOutputStream(destFile))
		{
			
			if (isBinFormat)
			{
				log.info("Generating BIN Format with address ${}", orgAddress); 
				
				byte[] decoded = Hex.decodeHex(orgAddress);
				
				// 0x3000 = 768 octets				
				byte[] header = { 0x00, 0x03, 0x00, decoded[0], decoded[1]};
			
				
				log.info("BIN Header : {}", Hex.encodeHexString(header));
				
				out.write(header);
				
			}
			else
			{
				log.info("Generating RAW Format", orgAddress);
			}
			
			log.info("Converting FNT file {} ...", fntFIle);
			
			log.info("Converting only this chars : {} ", convertedChars.toCharArray());
			
			
			char currentTargetChar = 0x20;
			int internalCharmap = 0;
			for (int index = 0; index < 128; index++) // 128 chars composés de 8 octets
			{
				byte[] currentData = in.readNBytes(8); // on lit 8 octets
				
				
				if ((index < 0x40 || index > 0x5F))				
				{			
					if (isConvertedChar(currentTargetChar))
					{
					  
					  log.info("#{} - ${} - CHAR [{}]", internalCharmap, Integer.toHexString(internalCharmap), currentTargetChar);	
					  ArrayUtils.reverse(currentData); // on les inverse
					  out.write(currentData); // on les écrits
					  internalCharmap++;
					}  
					currentTargetChar++;
				}
			}
			
			if (isBinFormat)
			{							
				byte[] data = new byte[5]; // 8 bytes at 0x00
				data[0] = (byte) 0xFF;
				log.info("Writing BIN trailer : {}", Hex.encodeHexString(data));
				out.write(data);
			}
			out.flush();
			log.info("File is converted into {}", destFile);
			log.info("File size : {} bytes", destFile.length());
		}
		catch (IOException | DecoderException e)
		{
			log.error(e.getMessage());
		}

	}

	private boolean isConvertedChar(char charValue)
	{
		if (StringUtils.isAllBlank(convertedChars))
		{
			return true;
		}
		else
		{
			for(char c : convertedChars.toCharArray())
			{
				if (charValue == c)
				{					
					return true;
				}
			}
			return false;
		}
	}

}