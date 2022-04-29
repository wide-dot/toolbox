package fr.fxjavadevblog.to8bs;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.util.Arrays;

import lombok.extern.slf4j.Slf4j;
import picocli.CommandLine;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;

@Command(name = "bootsectorbuilder", description = "build a bootsector for TO8")
@Slf4j
public class MainCommand implements Runnable
{
	// signature : "BASIC2"
	protected static final byte[] SIGNATURE = { 0x42, 0x41, 0x53, 0x49, 0x43, 0x32 };
	protected static final byte SIGNATURE_CHECK_SUM = 0x6C;
	protected static final byte CHECK_SUM_INIT_VALUE = 0x55;

	@Option(names = { "-b", "--boot-bin-raw" }, paramLabel = "Boot BIN RAW Source File", description = "the BIN file")
	File bootFile;

	@Option(names = { "-o", "--output-fd" }, paramLabel = "Destination File", description = "RAW file of the 255 bytes of the bootsector")
	File destFile;
	
	@Option(names = { "-d", "--data-file"}, paramLabel = "Data File", description = "Data file")
	File dataFile;
	
	@Option(names = { "-p", "--prog-raw-file"}, paramLabel = "Bin File", description = "Data file")
	File progFile;

	public static void main(String[] args)
	{
		CommandLine cmdLine = new CommandLine(new MainCommand());
		cmdLine.execute(args);
	}

	@Override
	public void run()
	{
		log.info("Building a TO8 bootsector");
		log.info("Converting {} into {}", bootFile, destFile);
		log.info("progFile : {}", progFile);
		log.info("dataFile : {}", dataFile);

		byte[] finalDisk  = new byte[ 2 * 80 * 16 * 256]; // 640 Ko, 1 disquette double-face
		Arrays.fill(finalDisk, (byte) 0x00);
		
		byte[] bootSector = initBootSector();	
		log.info("Signature data : {}", hexa(SIGNATURE));
		log.info("Signature checksum : 0x{}", hexa(SIGNATURE_CHECK_SUM));

		try
		{
			byte[] sourceBinData = loadBinData();		
			byte checkSum = (byte) (CHECK_SUM_INIT_VALUE + SIGNATURE_CHECK_SUM);
			checkSum = insertBin(bootSector, checkSum, sourceBinData);
			insertSignature(bootSector, SIGNATURE);
			insertChecksum(bootSector, checkSum);	
			if (dataFile != null) insert(dataFile, bootSector,128);
			copyBootSectorOnDisk(finalDisk, bootSector);
			if (progFile != null) insert(progFile, finalDisk,256);	
			writeDisk(finalDisk);
			log.info("DISK written : {} ", destFile);
		}
		catch (IOException e)
		{
			log.error(e.getMessage());
		}

	}

	/**
	 * insert des données dans le 2ème secteur, piste 0.
	 * 
	 * @param diskData
	 * @throws IOException
	 */
	private void insert(File file, byte[] dest, int insertAt) throws IOException
	{
		byte[] sourceData = Files.readAllBytes(file.toPath());
		for(int i = 0; i < sourceData.length ; i++)
		{
			dest[insertAt+i] = sourceData[i];
		}	
	}
	
	
	private void copyBootSectorOnDisk(byte[] disk, byte[] bootsector)
	{
		for(int i = 0; i < bootsector.length ; i++)
		{
			disk[i] = bootsector[i];
		}
	}

	private void writeDisk(byte[] bootSector) throws IOException
	{
		Files.write(destFile.toPath(), bootSector, StandardOpenOption.CREATE);
	}

	private byte[] loadBinData() throws IOException
	{
		byte[] sourceBinData = Files.readAllBytes(bootFile.toPath());
		log.info("Source BIN length : {} bytes", sourceBinData.length);
		return sourceBinData;
	}

	private byte[] initBootSector()
	{
		byte[] bootSector = new byte[256];
		Arrays.fill(bootSector, (byte) 0x00);
		return bootSector;
	}

	private void insertChecksum(byte[] bootSector, byte checkSum)
	{
		bootSector[127] = checkSum;
		log.info("Checksum : 0x{}", hexa(checkSum));
	}

	private void insertSignature(byte[] bootSector, byte[] signature)
	{
		// placement de la signature à partir de l'octet 120 jusqu'à 125 inclus

		for (int i = 0; i < signature.length; i++)
		{
			bootSector[120 + i] = signature[i];
		}
	}

	private byte insertBin(byte[] bootSector, byte checkSum, byte[] sourceBinData)
	{
		int sourceIndex = 0;

		
		for (int i = 0; i < bootSector.length; i++)
		{
			byte finalByte = 0x00;

			if (i < 120 && sourceIndex < sourceBinData.length)
			{
				// placement du programme de 0 à 119 : avec complément à 2
				byte data = sourceBinData[sourceIndex++];
				checkSum += data; // la checkSum est calculée sur l'octet réel et non pas sur le complément à deux.
				finalByte = twosComplement(data); // complément à 2
				log.info("BIN offset {} : {} -> {}", i, hexa(data), hexa(finalByte));

			}
			else if (i > 127 && sourceIndex < sourceBinData.length)
			{
				finalByte = sourceBinData[sourceIndex++];
				// pas de checkSum à calculer sur cette partie, ni de transformation en complément à deux.
			}

			bootSector[i] = finalByte;
		}
		return checkSum;
	}

	private byte twosComplement(byte b)
	{
		return (byte) (256 - b);
	}

	private String hexa(byte value)
	{
		return String.format("%02X", value);
	}

	private String hexa(byte[] values)
	{
		StringBuilder sb = new StringBuilder();
		for (byte b : values)
		{
			sb.append(hexa(b)).append(" ");
		}
		return sb.toString().trim();
	}

}