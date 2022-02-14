package com.widedot.to8.fntconv;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

import org.apache.commons.lang3.ArrayUtils;

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
		log.info("Converting FNT file {}", fntFIle);
		try (InputStream in = new FileInputStream(fntFIle); OutputStream out = new FileOutputStream(destFile))
		{
			for (int index = 0; index < 128; index++) // 128 chars composés de 8 octets
			{
				byte[] currentData = in.readNBytes(8); // on lit 8 octets
				if (index >= 0x40 && index <= 0x5F)
				{
					log.info("Ignoring {}",index);
				}
				else
				{
					log.info("Converting char #{} : {}", index, (char) (0x20 + index));					
					ArrayUtils.reverse(currentData); // on les inverse
					out.write(currentData); // on les écrits
				}
			}
			log.info("File converted into {}", destFile);
		}
		catch (IOException e)
		{
			log.error(e.getMessage());
		}

	}

}