package com.cyberbasslord.lightforge;

import java.io.File;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;

/** Real filesystem success/failure for the native delete acknowledgement boundary. */
public final class AndroidProjectDeletionTest {
    private static int checks;
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("lightforge-project-delete-");
        try{
            Path outside=Files.createDirectory(root.resolve("outside")),preserved=outside.resolve("preserved.txt");
            Files.write(preserved,new byte[]{1,2,3});
            Path project=Files.createDirectory(root.resolve("project"));
            Path nested=Files.createDirectory(project.resolve("nested"));Files.write(nested.resolve("project.json"),new byte[]{4});
            Files.createSymbolicLink(project.resolve("outside-link"),outside);
            Files.createSymbolicLink(project.resolve("missing-link"),root.resolve("missing"));
            MainActivity.deleteProjectFiles(project.toFile());
            check(!Files.exists(project),"Successful delete retained the project");
            check(Files.isRegularFile(preserved)&&Files.size(preserved)==3,"Deletion traversed a project symlink");
            MainActivity.deleteProjectFiles(project.toFile());checks++;

            // Introduce a real file just after enumeration. The operating
            // system must reject the final nonempty-directory deletion after
            // the listed files were removed, even when tests run as root.
            Path partial=Files.createDirectory(root.resolve("partial-project"));Files.write(partial.resolve("project.json"),new byte[]{5});
            File changingDirectory=new File(partial.toString()){
                @Override public File[] listFiles(){
                    File[] before=super.listFiles();
                    try{Files.write(partial.resolve("arrived-after-enumeration"),new byte[]{6});}
                    catch(IOException error){throw new UncheckedIOException(error);}
                    return before;
                }
            };
            try{MainActivity.deleteProjectFiles(changingDirectory);throw new AssertionError("Partial delete was acknowledged as success");}
            catch(IOException expected){
                check(expected.getMessage().contains("could not be fully removed")&&expected.getMessage().contains("may already have been deleted"),"Partial failure was misreported");
                check(expected.getCause() instanceof java.nio.file.DirectoryNotEmptyException,"Actual filesystem failure cause was lost");
            }
            check(Files.isDirectory(partial)&&!Files.exists(partial.resolve("project.json"))&&Files.exists(partial.resolve("arrived-after-enumeration")),"Fixture did not exercise partial deletion");
            MainActivity.deleteProjectFiles(partial.toFile());
            check(!Files.exists(partial),"Retry failed after the concurrent write ended");
            System.out.println("PASS: "+checks+" production project deletion checks");
        }finally{MainActivity.deleteProjectFiles(root.toFile());}
    }
}
