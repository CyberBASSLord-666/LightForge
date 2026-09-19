package com.cyberbasslord.lightforge;

import java.io.File;
import java.io.IOException;
import java.nio.file.DirectoryNotEmptyException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/** Process-start-only recovery of identifiable private GAME PCM, never live-task cleanup. */
final class NativeGamePassageCleanup {
    private static final String UUID="[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}";
    private NativeGamePassageCleanup() {}

    static final class Result {
        int removedInputs,removedDirectories,failures;
    }

    /**
     * Only Application.onCreate may call this, before any Activity or Service
     * can create a task. No recursion, file contents, audio names or logs.
     * Foreign entries and links are retained, including links with owned names.
     */
    static Result recover(File appCache) {
        Result result=new Result();
        try {
            if(appCache==null)throw new IOException("Cache unavailable");
            File cache=appCache.getCanonicalFile();
            if(!cache.isDirectory())throw new IOException("Cache unavailable");
            File root=new File(cache,"native-game-passages");
            if(!Files.exists(root.toPath(),LinkOption.NOFOLLOW_LINKS))return result;
            if(!directDirectory(cache,root))throw new IOException("Passage root unavailable");
            for(File job:children(root)) {
                if(!job.getName().matches(UUID)||!directDirectory(root,job))continue;
                recoverJob(job,result);
                removeEmpty(job,result);
            }
        } catch(IOException|SecurityException failure) { result.failures++; }
        return result;
    }

    private static void recoverJob(File job,Result result) {
        try {
            for(File task:children(job)) {
                if(!task.getName().matches(UUID)||!directDirectory(job,task))continue;
                recoverTask(task,result);
                removeEmpty(task,result);
            }
        } catch(IOException|SecurityException failure) { result.failures++; }
    }

    private static void recoverTask(File task,Result result) {
        try {
            for(File input:children(task)) {
                if(!input.getName().matches(UUID+"\\.input"))continue;
                Path path=input.toPath();
                if(Files.isSymbolicLink(path)||!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS))continue;
                if(!directPath(task,input))continue;
                try { Files.delete(path);result.removedInputs++; }
                catch(IOException|SecurityException failure) { result.failures++; }
            }
        } catch(IOException|SecurityException failure) { result.failures++; }
    }

    private static File[] children(File directory)throws IOException {
        File[] entries=directory.listFiles();
        if(entries==null)throw new IOException("Passage directory unavailable");
        return entries;
    }

    private static boolean directDirectory(File parent,File child)throws IOException {
        return !Files.isSymbolicLink(child.toPath())
            &&Files.isDirectory(child.toPath(),LinkOption.NOFOLLOW_LINKS)&&directPath(parent,child);
    }

    private static boolean directPath(File parent,File child)throws IOException {
        File canonical=child.getCanonicalFile();
        return canonical.equals(child.getAbsoluteFile())&&parent.equals(canonical.getParentFile());
    }

    private static void removeEmpty(File directory,Result result) {
        try { Files.delete(directory.toPath());result.removedDirectories++; }
        catch(DirectoryNotEmptyException foreignOrFailedInput) { /* Preserve all unrecognized contents. */ }
        catch(IOException|SecurityException failure) { result.failures++; }
    }
}
