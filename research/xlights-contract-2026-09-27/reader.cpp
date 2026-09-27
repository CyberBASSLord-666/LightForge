#include "FSEQFile.h"
#include <memory>
#include <cstdio>
int main(int argc,char **argv) {
 if(argc!=3)return 2;
 std::unique_ptr<FSEQFile> file(FSEQFile::openFSEQFile(argv[1]));
 if(!file||file->getChannelCount()!=200||file->getVersionMajor()!=2)return 3;
 FILE *out=fopen(argv[2],"wb");if(!out)return 4;
 file->prepareRead({{0,200}});
 for(uint32_t n=0;n<file->getNumFrames();++n) {
  std::unique_ptr<FSEQFile::FrameData> frame(file->getFrame(n));uint8_t bytes[200]={};
  if(!frame||!frame->readFrame(bytes,200)||fwrite(bytes,1,200,out)!=200)return 5;
 }
 fclose(out);
 printf("{\"version\":\"%d.%d\",\"channels\":%llu,\"frames\":%llu,\"stepMs\":%d,\"media\":\"%s\"}\n",file->getVersionMajor(),file->getVersionMinor(),(unsigned long long)file->getChannelCount(),(unsigned long long)file->getNumFrames(),file->getStepTime(),file->getMediaFilename().c_str());
}
