package com.cyberbasslord.lightforge;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.stream.Stream;

public final class NativeGamePassageCleanupTest {
    private static final String JOB="11111111-1111-4111-8111-111111111111",TASK="22222222-2222-4222-8222-222222222222",TOKEN="33333333-3333-4333-8333-333333333333";
    private static void require(boolean value,String detail) { if(!value)throw new AssertionError(detail); }
    private static Path input(Path cache,String job,String task) throws Exception {
        Path directory=cache.resolve("native-game-passages").resolve(job).resolve(task);
        Files.createDirectories(directory);Path input=directory.resolve(TOKEN+".input");Files.write(input,new byte[]{1,2,3,4});return input;
    }
    public static void main(String[] args)throws Exception {
        Path base=Files.createTempDirectory("lightforge-game-cache-test-");
        try {
            if(args.length>0&&"failure-hook".equals(args[0])) {
                Path cache=Files.createDirectory(base.resolve("cache"));Files.write(cache.resolve("native-game-passages"),new byte[]{7});
                android.app.Application.cacheDirectory=cache.toFile();new LightForgeApplication().onCreate();
                require(AppDiagnostics.messages.size()==1,"cleanup failure was silent");
                require(!AppDiagnostics.messages.get(0).contains(base.toString()),"private cache path entered diagnostics");
                require(Files.readAllBytes(cache.resolve("native-game-passages"))[0]==7,"foreign root file changed");
            } else {
                Path cache=Files.createDirectory(base.resolve("cache"));Path owned=input(cache,JOB,TASK);
                NativeGamePassageCleanup.Result cleaned=NativeGamePassageCleanup.recover(cache.toFile());
                require(cleaned.removedInputs==1&&cleaned.removedDirectories==2&&cleaned.failures==0,"owned orphan was not removed");
                require(!Files.exists(owned),"orphan survived");
                Path foreign=input(cache,"foreign-job",TASK),wrongTask=input(cache,JOB,"foreign-task"),recognized=input(cache,JOB,TASK);
                Path keep=recognized.getParent().resolve("notes.txt");Files.write(keep,new byte[]{9});
                Path wrongSuffix=recognized.getParent().resolve(TOKEN+".bin");Files.write(wrongSuffix,new byte[]{8});
                cleaned=NativeGamePassageCleanup.recover(cache.toFile());
                require(cleaned.removedInputs==1&&cleaned.failures==0,"mixed folder cleanup failed");
                require(Files.exists(foreign)&&Files.exists(wrongTask)&&Files.exists(keep)&&Files.exists(wrongSuffix),"unrecognized content removed");
                Path outside=Files.createDirectory(base.resolve("outside")),outsideFile=outside.resolve(TOKEN+".input");Files.write(outsideFile,new byte[]{5});
                Path inputLink=recognized;Files.createSymbolicLink(inputLink,outsideFile);
                Path taskLink=cache.resolve("native-game-passages").resolve(JOB).resolve("44444444-4444-4444-8444-444444444444");Files.createSymbolicLink(taskLink,outside);
                Path jobLink=cache.resolve("native-game-passages").resolve("55555555-5555-4555-8555-555555555555");Files.createSymbolicLink(jobLink,outside);
                cleaned=NativeGamePassageCleanup.recover(cache.toFile());
                require(cleaned.removedInputs==0&&Files.exists(outsideFile),"symlink target was traversed");
                require(Files.isSymbolicLink(inputLink)&&Files.isSymbolicLink(taskLink)&&Files.isSymbolicLink(jobLink),"links were deleted");
                Path linkedCache=Files.createDirectory(base.resolve("linked-cache"));Files.createSymbolicLink(linkedCache.resolve("native-game-passages"),outside);
                require(NativeGamePassageCleanup.recover(linkedCache.toFile()).failures==1&&Files.exists(outsideFile),"linked root was followed");
                Path freshCache=Files.createDirectory(base.resolve("fresh-cache"));
                require(NativeGamePassageCleanup.recover(freshCache.toFile()).failures==0,"missing root was treated as failure");
                require(NativeGamePassageCleanup.recover(outsideFile.toFile()).failures==1,"invalid cache root was accepted");
                Path onceCache=Files.createDirectory(base.resolve("once-cache")),before=input(onceCache,JOB,TASK);
                android.app.Application.cacheDirectory=onceCache.toFile();new LightForgeApplication().onCreate();require(!Files.exists(before),"startup did not scavenge");
                Path live=input(onceCache,JOB,TASK);new LightForgeApplication().onCreate();require(Files.exists(live),"second initialization scavenged a live process task");
            }
            System.out.println("PASS: process-start-only native GAME private passage cleanup");
        } finally {
            try(Stream<Path> paths=Files.walk(base)) { for(Path path:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator)Files.deleteIfExists(path); }
        }
    }
}
