package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Crash evidence must match a durable native lease before disabling a runtime. */
public final class NativeRuntimeGuardTest {
    private static int checks;
    private static final long START=1700000000000L;
    public static void main(String[] args)throws Exception {
        File root=args.length==0?Files.createTempDirectory("native-runtime-guard-test").toFile():new File(args[0]);root.mkdirs();
        try{
            completedAndCancelled(root);nativeCrash(root);unrelatedExits(root);ownership(root);boundedStorage(root);
            System.out.println("PASS: "+checks+" native runtime guard checks; confirmed native crash, runtime/app updates, cancellation, ownership, timestamp/PID boundaries and corrupt state.");
        }finally{remove(root);}
    }
    private static void completedAndCancelled(File root)throws Exception {
        NativeRuntimeGuard guard=new NativeRuntimeGuard(new File(root,"complete"),"20203-1.25.1");
        require(guard.state()==null,"empty guard");
        String token=guard.begin(100,START);guard.end(token);
        require(guard.state()==null,"normal return/cancel/Java exception releases marker");
        require(guard.reconcile(Collections.singletonList(exit(100,5,4,START+10,true)),START+20),"completed native work cannot blame a later unrelated crash");
    }
    private static void nativeCrash(File root)throws Exception {
        File directory=new File(root,"native");
        NativeRuntimeGuard first=new NativeRuntimeGuard(directory,"20203-1.25.1");
        first.begin(200,START);
        NativeRuntimeGuard restart=new NativeRuntimeGuard(directory,"20203-1.25.1");
        require(!restart.reconcile(Collections.singletonList(exit(200,5,4,START+1200,true)),START+5000),"SIGILL during owned native work selects compatibility");
        require(restart.state().disabled&&restart.state().status==4,"signal retained in durable disabled state");
        require(!new NativeRuntimeGuard(directory,"20203-1.25.1").reconcile(Collections.emptyList(),START+10000),"disabled decision survives further restarts without retained exit history");
        expectIo(()->restart.begin(300,START+10000),"direct start cannot bypass native disable");
        require(new NativeRuntimeGuard(directory,"20203-1.26.0").reconcile(Collections.emptyList(),START+10000),"new native runtime may be tried");
        require(new NativeRuntimeGuard(directory,"20204-1.25.1").reconcile(Collections.emptyList(),START+10000),"new app build may be tried");
        NativeRuntimeGuard update=new NativeRuntimeGuard(directory,"20204-1.25.1");String token=update.begin(400,START+10000);update.end(token);
        require(update.state()==null,"new app can complete and release its own lease");
        NativeRuntimeGuard noSignal=new NativeRuntimeGuard(new File(root,"native-nosignal"),"20203-1.25.1");noSignal.begin(201,START);
        require(!noSignal.reconcile(Collections.singletonList(exit(201,5,0,START+1000,true)),START+2000),"Android-confirmed native crash still counts when status was not retained");
    }
    private static void unrelatedExits(File root)throws Exception {
        NativeRuntimeGuard guard=new NativeRuntimeGuard(new File(root,"unrelated"),"20203-1.25.1");guard.begin(500,START);
        List<NativeRuntimeGuard.Exit> ignored=Arrays.asList(
            exit(500,4,0,START+100,true), // Java crash
            exit(500,3,9,START+100,true), // low memory
            exit(500,10,0,START+100,true), // user request / force stop
            exit(500,1,0,START+100,true), // normal process exit
            exit(501,5,4,START+100,true), // another process ID
            exit(500,5,4,START+100,false), // renderer or another app process
            exit(500,5,4,START-1,true), // older PID reuse
            exit(500,5,4,START+3000,true)); // future timestamp
        require(guard.reconcile(ignored,START+2000),"OOM, Java errors, force stop, wrong PID/process and time mismatches retain native availability");
        require(guard.reconcile(Collections.singletonList(exit(500,5,4,START+NativeRuntimeGuard.MAX_EXECUTION_MS+1,true)),START+NativeRuntimeGuard.MAX_EXECUTION_MS+1000),"crash outside bounded execution window ignored");
        require(guard.reconcile(Collections.singletonList(exit(500,5,4,START+100,true)),START-1),"wall clock reversal does not infer a native crash");
        require(guard.reconcile(Collections.emptyList(),START+1000),"missing exit evidence does not select compatibility");
        require(!guard.state().disabled,"ignored evidence is not persisted as disabled");
    }
    private static void ownership(File root)throws Exception {
        File directory=new File(root,"ownership");
        NativeRuntimeGuard retiring=new NativeRuntimeGuard(directory,"20203-1.25.1"),replacement=new NativeRuntimeGuard(directory,"20203-1.25.1");
        String old=retiring.begin(600,START),current=replacement.begin(600,START+1000);
        retiring.end(old);require(current.equals(replacement.state().token),"old service cannot remove replacement marker");
        replacement.end(current);require(retiring.state()==null,"owning completion removes marker");
    }
    private static void boundedStorage(File root)throws Exception {
        File directory=new File(root,"corrupt");directory.mkdirs();File marker=new File(directory,"native-runtime-guard.bin");
        NativeRuntimeGuard guard=new NativeRuntimeGuard(directory,"20203-1.25.1");
        Files.write(marker.toPath(),new byte[2048]);expectIo(()->guard.state(),"oversized marker rejected");
        Files.write(marker.toPath(),new byte[]{1,2,3});expectIo(()->guard.state(),"truncated marker rejected");
        marker.delete();File blocked=new File(root,"blocked");Files.write(blocked.toPath(),new byte[]{1});
        expectIo(()->new NativeRuntimeGuard(blocked,"20203-1.25.1").begin(700,START),"failed durable write must stop before JNI");
    }
    private static NativeRuntimeGuard.Exit exit(int pid,int reason,int status,long time,boolean main){return new NativeRuntimeGuard.Exit(pid,reason,status,time,main);}
    private interface Action {void run()throws Exception;}
    private static void expectIo(Action action,String message)throws Exception{try{action.run();throw new AssertionError(message);}catch(IOException expected){checks++;}}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    private static void remove(File file)throws IOException{if(file.isDirectory())for(File child:Objects.requireNonNull(file.listFiles()))remove(child);Files.deleteIfExists(file.toPath());}
}
