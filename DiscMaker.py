# Filename  : DiscMaker.py
# Authors   : Aleff Correa
# Version   : 1.12

import argparse, os, collections
import subprocess
import xml.etree.ElementTree 
from string import Template

SCRIPT_VERSION = "1.12"

#Label file defines
headerTextHuC =("/**\n" + " * CD-Rom Data/Overlay reference labels\n"
                " * Generated by pyDiscMaker Version " + SCRIPT_VERSION + "\n"
                " * (C) 2019 The DiscMaker Project\n"
                " **/\n"
                "#ifndef _DISCMAKER_LABELS_H\n"
                "#define _DISCMAKER_LABELS_H\n\n")

headerTextAsm =(";  CD-Rom Data/Overlay reference labels\n"
                ";  Generated by pyDiscMaker Version " + SCRIPT_VERSION + "\n"
                "; (C) 2019 The DiscMaker Project\n"
                "\n")

sectorTextHuC =     Template("#define ADDR_$name $value\n")
byteSizeTextHuC =   Template("#define SIZE_$name $value\n")
sectorSizeTextHuC = Template("#define SECSIZE_$name $value\n")
blobOffsetTextHuC = Template("#define OFFSET_$name $value\n")
blobCommentHuC =    Template("\n/*Blob $name: */\n")
blobEndCommentHuC = Template("/*End of blob $name. */\n")

sectorTextAsm =     Template("_ADDR_$name = $value\n")
byteSizeTextAsm =   Template("_SIZE_$name = $value\n")
sectorSizeTextAsm = Template("_SECSIZE_$name = $value\n")
blobOffsetTextAsm = Template("_OFFSET_$name = $value\n")
blobCommentAsm =    Template("\n; Blob $name:")
blobEndCommentAsm = Template("; End of blob $name.\n")


#Executes a ceiling division. (integer only)
def div_ceil_int(n, d):
  return (n + (d - 1)) // d

class Blob(object):
  def __init__(self, nodes):
    self.size = 0
    self.address = 0
    self.sectors = 0
    self.name = None
    self.nodes = nodes
  
class Index(object):
  def __init__(self, size):
    self.address = -1
    self.blobaddress = 0
    if (size != -1):
      self.padding = -1 * ((size % 2048) - 2048)
      if (self.padding == 2048):
        self.padding = 0
      self.sectors = div_ceil_int(size, 2048)
    else:
      self.padding = 0
      self.sectors = 1
  
class DummyIndex(Index):
  Number = 0
  def __init__(self, fileLabel, size):
    self.size = size
    self.name = ("Dummy_" + str(DummyIndex.Number)) if fileLabel is None else fileLabel
    DummyIndex.Number += 1
    
    Index.__init__(self, size)
    
  def getData(self):
    return b"\0" * self.size

class FileIndex(Index):
  def __init__(self, filePath, fileLabel):
    if os.path.isfile(filePath) is False:
      raise OSError("File not found or Not a File: " + filePath) #not a valid file path
    self.name = os.path.splitext(os.path.basename(filePath))[0] if fileLabel is None else fileLabel
    self.filePath = filePath
    self.size = os.path.getsize(filePath)
    
    Index.__init__(self, self.size)
  
  #Reads referenced file from disk to RAM
  def getData(self):
    with open(self.filePath, "rb") as file:
      return file.read(self.size)
      
class ProgramIndex(Index):
  def __init__(self, command, filePath, fileLabel, outputFilename, isSinglePass):
    if os.path.isfile(filePath) is False:
      raise OSError("Program File not found or Not a File: " + filePath) #not a valid file path
    self.fileName = os.path.splitext(os.path.basename(filePath))[0]
    self.name = self.fileName if fileLabel is None else fileLabel
    self.command = command
    self.filePath = filePath
    self.outputDir = os.path.dirname(self.filePath)
    if (self.outputDir != ""):
      self.outputDir = self.outputDir + "\\"
    self.outputPath = self.outputDir + outputFilename
    Index.__init__(self, -1)
    #The size starts at -1 so we can know it hasn't been compiled yet.
    self.size = -1
    self.isSinglePass = isSinglePass
    
  def compile(self):
    #shellCommand = self.command + " " + self.filePath
    shellCommand = self.command.substitute(filePath = self.filePath, fileName = self.fileName)
    exitcode = subprocess.call(shellCommand, stdout = True, stderr = False, shell=True)
    #Exitcode is 0 if success (HuC/PCEAS). Supply error/success code values through xml?
    #if (exitcode != 0):
    if os.path.isfile(self.outputPath) is False:
      raise RuntimeError("Command " + shellCommand + " failed to compile. :(")
    if (self.size == -1):
      self.size = os.path.getsize(self.outputPath)
      self.padding = -1 * ((self.size % 2048) - 2048)
      if (self.padding == 2048):
        self.padding = 0
      self.sectors = div_ceil_int(self.size, 2048)
      
  def getData(self):
    with open(self.outputPath, "rb") as file:
      return file.read(self.size)

class DiscMaker(object):
  def __init__(self, targetPath, packListPath, isBankSized, offset, fileList):
    self.targetPath = None
    self.labelPath = None
    self.isBankSized = None
    self.offset = None
    self.hucLabels = None

    #For detecting last pass for single pass ProgIndexes.
    #Maybe something neat like a huge chain of sequential stuff could be done with this > 2?
    self.lastPass = 2
    
    self.packListPath = packListPath
    self.fileManifest = collections.OrderedDict()
    self.commandDict  = collections.OrderedDict()
    
    #Create CDROM entry manifest from XML Pack List (if exists)
    if (packListPath is not None):
      packList = xml.etree.ElementTree.parse(packListPath)
      list = packList.getroot()
      
      if (list.tag == "data"):
        #Get disc config from XML file.
        self.parseConfig(list)
        #Get compiler commands from XML file.
        self.parseCommands(list)
        #Walk through tree and get blobs/binaries in order
        self.fileManifest = self.parseDataList(list, None)

        #Calculate bogus label file for two-pass ProgIndexes
        self.calculateDiscOffsets()
        self.printReport(None, self.fileManifest, self.hucLabels, True)

        #Compile all non-single-pass ProgIndexes.
        #This gets us the real size/sector/padding of the programs,
        #while Single Pass programs should already have the size already.
        self.compileProgIndexes()

        #Calculate REAL offsets this time around.
        self.calculateDiscOffsets()

        #Generate true label file, and print it to terminal
        self.printReport(None, self.fileManifest, self.hucLabels, True)
        
        #Compile Two-Pass programs with correct offsets, and Single-Pass ones too.
        self.compileProgIndexes()

        #Finally, build the .bin CD-ROM data track.
        self.buildTrack()

      else:
        raise RuntimeError("Invalid .xml root tag " + list.tag + "!")
      
    #Legacy mode is no more, so no packlist = no disc
    else:
      raise RuntimeError("Please define the path to the .xml config file!")
    
  #Check for all config tags for the cfg attributes
  #Raises exception if a config attribute is multiply defined  
  def parseConfig(self, rootNode):
    for node in rootNode:
      if (node.tag == "config"):
        cfgoffset = node.attrib.get("start_offset")
        cfgoffunit = node.attrib.get("offset_unit")
        cfgbinpath = node.attrib.get("track_path")
        cfglabelpath = node.attrib.get("label_path")
        cfghucmode = node.attrib.get("huc_labels")
        
        if ( ((self.offset is not None)      and (cfgoffset is not None))
          or ((self.isBankSized is not None) and (cfgoffunit is not None))
          or ((self.targetPath is not None)  and (cfgbinpath is not None))
          or ((self.labelPath is not None) and (cfglabelpath is not None))
          or ((self.hucLabels is not None) and (cfghucmode is not None)) ):
          raise RuntimeError("Config attribute(s) multiply defined!")
          
        self.targetPath = cfgbinpath if cfgbinpath is not None else self.targetPath
        self.labelPath = cfglabelpath if cfglabelpath is not None else self.labelPath
        self.offset = int(cfgoffset) if cfgoffset is not None else None

        if (cfghucmode == "true" or cfghucmode == "True"):
          self.hucLabels = True
        elif (cfghucmode == "false" or cfghucmode == "False"):
          self.hucLabels = False
        elif (cfghucmode is not None):
          raise RuntimeError("Attribute \'huc_labels\' either True or False: " + cfgoffunit + " is invalid.")

        if (cfgoffunit == "sector"):
          self.isBankSized = False
        elif (cfgoffunit == "bank"):
          self.isBankSized = True
        elif (cfgoffunit is not None):
          raise RuntimeError("Attribute \'offset_unit\' not bank or sector: "+ cfgoffunit + " is invalid.")

    #endfor
    #Check for mandatory config attributes
    #if (self.offset is None):
    #  raise RuntimeError("Config attribute \'start_offset\' undefined! Please define it.")

    #Add default values for undefined optional cfg attributes
    self.offset = 0 if self.offset is None else self.offset
    self.targetPath = "data_track.iso" if self.targetPath is None else self.targetPath
    self.labelPath = "labels.asm" if self.labelPath is None else self.labelPath
    self.isBankSized = False if self.isBankSized is None else self.isBankSized
    self.hucLabels = True if self.hucLabels is None else self.hucLabels
    
    #Scale offset value by 4 if the offset unit is Bank instead of Sector
    self.offset = (self.offset * 4) if self.isBankSized else self.offset
  
  #Checks root for 'compiler' tags and stores it in its internal dictionary,
  # much like method parseConfig.
  def parseCommands(self, rootNode):
    for node in rootNode:
      if (node.tag == 'compiler'):
        compilerName = node.attrib.get('name')
        compilerCommand = node.attrib.get('command')
        
        if (compilerCommand is None or compilerName is None):
          raise RuntimeError("\'Compiler\' tag has attributes missing!")
        
        self.commandDict[compilerName] = Template(compilerCommand)
  
  #Goes recursively through blobs of data, creating nested OrderedDicts with
  #the blobs of data defined in the packlist XML.
  #Raises RuntimeError, ValueError, OSError (from FileIndex)
  def parseDataList(self, rootNode, baseName):
    nodeManifest = collections.OrderedDict()
    unlabeledBlobIndex = 0
    
    #Appends underscore to baseName
    #(skips it if node is root)
    if (baseName is None):
      baseName = ""
    else:
      baseName = baseName + "_"
    
    for node in rootNode:
      newKey   = ""
      newEntry = None
      
      #Blobs have a subtree of binaries, so we use recursion to build 'em.
      if (node.tag == "blob"):
        newKey = node.attrib.get("label")
        if (newKey is None):
          newKey = "blob" + unlabeledBlobIndex
          unlabeledBlobIndex += 1
        newEntry = Blob(self.parseDataList(node, baseName + newKey))
        
        if (len(newEntry.nodes) == 0):
          raise RuntimeError("Blob " + newKey + " is empty!!")
        
      elif (node.tag == "binary"):
        binpath  = node.attrib.get("path")
        binlabel = node.attrib.get("label")
        if (binpath is None):
          raise RuntimeError("Binary in XML has no path!")
        newEntry = FileIndex(binpath, binlabel)
        newKey = newEntry.name
        
      elif (node.tag == "dummy"):
        dummysize = 0 if node.attrib.get("size") is None else int(node.attrib.get("size"))
        dummylabel = node.attrib.get("label") 
        newEntry = DummyIndex(dummylabel, dummysize)
        newKey = newEntry.name
        
      elif (node.tag == "program"):
        progCommand = node.attrib.get("compiler")
        progPath = node.attrib.get("path")
        progLabel = node.attrib.get("label")
        progOutLabel = node.attrib.get("output")
        singlePassStr = node.attrib.get("size")

        if (progCommand is None or progCommand in self.commandDict is False):
          raise RuntimeError("Compiler command missing or undefined!")
        progCommand = self.commandDict[progCommand]

        if (singlePassStr is None):
          singlePass = False
        elif (singlePassStr == "True" or singlePassStr == "true"):
          singlePass = True
        else:
          raise RuntimeError("SinglePass can only be True or False!")
      
        if (progOutLabel is None):
          raise RuntimeError("Output filename undefined in program tag! This is required.")
        newEntry = ProgramIndex(progCommand, progPath, progLabel, progOutLabel, singlePass)
        newKey = newEntry.name
        
      else:
        continue
      #endif 
      
      #Append node name to basename, if not blob
      #if (type(newEntry) is DummyIndex) or (type(newEntry) is FileIndex):
      newEntry.name = baseName + newKey
      
      #Check if node tag was multiply defined in its scope @ XML file
      if (newKey in nodeManifest):
          raise RuntimeError("Duplicate label" + newEntry.name + "inside scope at " + rootNode.tag + "!")
      
      #Finally add the binary node OR binary blob to the current dict blob.
      nodeManifest[newKey] = newEntry
    #endfor
    return nodeManifest
  #end
    
  #Calculates offsets for the whole disc.
  def calculateDiscOffsets(self):
    currentSector = self.offset
    for name, obj in self.fileManifest.items():
      #Single binary object: Simple sector update
      if(type(obj) is not Blob):
        #save sector insertion position for later reference
        obj.address = currentSector 
        #update sector pointer
        currentSector += obj.sectors
      
      #Binary blob: All files padded as a single one.
      #Since we can't figure out sizes/sectors as easily with nested nodes,
      #we calculate them here.
      else:
        #Get blob of data and size, and update currentSector
        obj.address = currentSector
        currentSector, blobsize = self.calculateBlobOffsets(obj.nodes, currentSector)
        obj.sectors = currentSector - obj.address + 1
        obj.size = blobsize
        #Calculate padding to decide if it occupies an "extra" sector on disc
        blobpadding = -1 * ((blobsize % 2048) - 2048)
        if (blobpadding != 2048):
          currentSector += 1

    #If track final size is less than 150 sectors (2 seconds), then
    #we append a dummy file to meet CDROM standard minimum track size.
    if (currentSector < 150):
      remainingSpace = (150 - currentSector) * 2048
      #Check so first pass dummy gets 0 size.
      if ("_CDROM_Specs_Padding" in self.fileManifest):
        paddingDummy = DummyIndex("_CDROM_Specs_Padding", remainingSpace)
      else:
        paddingDummy = DummyIndex("_CDROM_Specs_Padding", 0)
      paddingDummy.address = currentSector
      self.fileManifest[paddingDummy.name] = paddingDummy

  #Uses recursion to calculate sizes/sectors for data inside blob
  def calculateBlobOffsets(self, rootNode, sector, blobptr = 0):    
    for key, node in rootNode.items():
      if (type(node) is ProgramIndex):
        node.address = sector
        node.blobaddress = blobptr
        #don't recalculate sector size if we haven't compiled the program yet
        if (node.size != -1):
          #Calculates the size of the additions relative to the current
          #sector byte pointer so we can figure out how many more sectors
          #we're using cleanly.
          curSecPtr = blobptr % 2048
          curSecPtr += node.size
          sector += curSecPtr // 2048
          #The pointer only moves if there's actual data in the progindex
          blobptr += node.size

      elif (type(node) is DummyIndex) or (type(node) is FileIndex):
        #Save current sector reference for later use
        node.address = sector
        node.blobaddress = blobptr
        #Append node data.

        #Relculate sector size
        curSecPtr = blobptr % 2048
        curSecPtr += node.size
        sector += curSecPtr // 2048
        #Blobptr is both the total size of the blob and
        #the address of the next binary relative to blob start
        blobptr += node.size

      else:
        #Use recursion to calculate child node's offsets.
        node.address = sector

        blobptrStart = blobptr
        sector, blobptrEnd = self.calculateBlobOffsets(node.nodes, sector, blobptr)
        node.size = blobptrEnd - blobptrStart
        blobptr = blobptrEnd
        node.sectors = sector - node.address + 1
  
    return (sector, blobptr)

  def compileProgIndexes(self, currentPass = 1):
    for name, obj in self.fileManifest.items():
      if (type(obj) is ProgramIndex):
        #if it's single pass then the obj.size is already correct
        #and therefore compiling it more than once is unneeded.
        if (obj.isSinglePass is True and currentPass == self.lastPass):
          obj.compile()
        elif (obj.isSinglePass is False):
          obj.compile()


  #Call this to build the .bin image 
  #from the already parsed disc node tree
  def buildTrack(self):
    with open(self.targetPath, "wb") as track:
      for name, obj in self.fileManifest.items():
        #Single binary object: Write and pad.
        if(type(obj) is not Blob):
          #save sector insertion pos for later reference
          #copy data to mastered track file
          track.write(obj.getData())
          #pad to 2048 aligned sectors
          if (obj.padding > 0):
            track.write(b"\0" * obj.padding)
          #update sector pointer
        
        #Binary blob: All files padded as a single one.
        else:
          #Get blob of data and size, and update currentSector
          blobdata = self.buildBlob(obj.nodes)
          blobsize = len(blobdata)
          track.write(blobdata)
          #Calculate padding with blob's total size, 2048b aligned
          blobpadding = -1 * ((blobsize % 2048) - 2048)
          if (blobpadding != 2048):
            track.write(b"\0" * blobpadding)
     
      #If overwriting a larger, old file, we need to
      #resize the file to clip off old remaining data.
      track.truncate()
    #close file

  #Uses recursion to return data from all 
  #binaries defined in the blob node.
  def buildBlob(self, rootNode, blobptr = 0):
    output = bytearray()
    
    for key, node in rootNode.items():
      if (type(node) is not Blob):
          output = output + node.getData()
      else:
        #Use recursion to get child node's data.
        data = self.buildBlob(node.nodes, blobptr)
        output += data
    return (output)
    
  #Outputs labels indicating size/addresses on the data track
  #in PCEAS2 friendly format.
  #This method is in a good need of a cleanup...
  #Recursive (run first with file=None to create file)
  def printReport(self, file, rootNode, isHuCHeader, isSilent=False, level=0):
    #Define the style of the label file (HuC header or PCEAS asm file)
    if isHuCHeader:
      headerText = headerTextHuC
      sectorText = sectorTextHuC
      byteSizeText = byteSizeTextHuC
      sectorSizeText = sectorSizeTextHuC
      blobOffsetText = blobOffsetTextHuC
      blobComment = blobCommentHuC
      blobEndComment = blobEndCommentHuC
    else:
      headerText = headerTextAsm
      sectorText = sectorTextAsm
      byteSizeText = byteSizeTextAsm
      sectorSizeText = sectorSizeTextAsm
      blobOffsetText = blobOffsetTextAsm
      blobComment = blobCommentAsm
      blobEndComment = blobEndCommentAsm
    
    if (file is None):   
      topLevel = True
      report = open(self.labelPath, "w")
      report.write(headerText)
      
      if (not isSilent):
        os.system('cls' if os.name == 'nt' else 'clear')
        print("*******************************")
        print("** DiscMaker " + SCRIPT_VERSION + " for Python **")
        print("{:*<65s}".format(""))
        print("*{:<63s}*".format(""))
        print("*{:^63s}*".format("C D R O M    T A B L E    O F    C O N T E N T S"))
        print("*{:<63s}*".format(""))
        print("{:*<65s}".format(""))
        print("* Addr ** #Sec **  Size  **            File Label               *")
        print("{:*<65s}".format(""))
    else:
      report = file
      topLevel = False
    
    for name, obj in rootNode.items():
      #top level = non-blob binary
      report.write(sectorText.substitute(name = obj.name, value = str(obj.address)))
      if (not topLevel) and (type(obj) is not Blob):
        report.write(blobOffsetText.substitute(name = obj.name, value = str(obj.blobaddress)))
      report.write(byteSizeText.substitute(name = obj.name, value = str(obj.size)))
      report.write(sectorSizeText.substitute(name = obj.name, value = str(obj.sectors)))
      if type(obj) is Blob:
        report.write(blobComment.substitute(name = obj.name))
      else:       
        report.write("\n")
      
      if (not isSilent) and topLevel and (type(obj) is not Blob):
        print("* {:<5d}** {:<5d}** {:<7d}** {:36.36s}*".format(obj.address, 
          obj.sectors, obj.size, obj.name))
      elif (not isSilent) and (not topLevel) and (type(obj) is not Blob):
        print("* {:<13d}** {:<7d}** {:36.36s}*".format(obj.blobaddress, 
          obj.size, obj.name))
      elif (not isSilent) and (type(obj) is Blob):
        print("* {:<5d}{:-<{lvl}s}+ {:-<{sz}s}*".format(
          obj.address, "", name, lvl = level, sz = 55 - level))

      #Recursively print out the node's children
      if (type(obj) is Blob):
        self.printReport(report, obj.nodes, isHuCHeader, isSilent, level + 2)
        
    if (not isSilent):
      if (level > 0): #58
        print("* {:<5s}{:<{lvl}s}+{:-<{sz}s}*".format(
            "", "", "", lvl = level-2, sz = 58 - level))
      else:
        print("{:*<65s}".format(""))
  
    if (level == 0):
      if isHuCHeader:
        report.write("\n#endif\n")
      report.truncate()
      report.close()
    else:
      report.write(blobEndComment.substitute(name = obj.name))
      
#Parse command line arguments                
legacyParser = argparse.ArgumentParser(
description = ("Appends all files specified in 2048 byte blocks "
  "(the size of a CDROM sector), appending zeroes when needed. "
  "It also makes a list of all files and respective sector addresses."
  ))
legacyParser.add_argument("packlist",
  help = "XML-formatted document specifying which files should be inserted "
  "into the CDROM data track, and their relative layout. ")

try:  
  args = legacyParser.parse_args()
  if (args.packlist is not None):  
    maker = DiscMaker(None, args.packlist, None, None, None)             
  else:
    raise RuntimeError("No XML or files specified. Use -h for help.")
except (ValueError) as err:
  print ("Could not parse numeric attribute! Check your XML file.")
  raise
except (Exception) as err:
  print (err)
  raise