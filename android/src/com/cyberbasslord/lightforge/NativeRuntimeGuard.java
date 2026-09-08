package com.cyberbasslord.lightforge;

import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Persists only a native execution lease, never project or audio data. */
final class NativeRuntimeGuard {
    static final long MAX_EXECUTION_MS=6*60*60*1000L;
    static final int NATIVE_CRASH=5;
    private static final int MAGIC=0x4c464e31,MAX_BYTES=1024;
    private final File file;
    private final String runtime;
    // All instances in the app process share ownership checks and atomic writes.
    private static final Object LOCK=new Object();

    static final class Exit {
        final int pid,reason,status;
        final long timestamp;
        final boolean mainProcess;
        Exit(int pid,int reason,int status,long timestamp,boolean mainProcess){this.pid=pid;this.reason=reason;this.status=status;this.timestamp=timestamp;this.mainProcess=mainProcess;}
    }
    static final class State {
        final String runtime,token;
        final int pid,status;
        final long beganAt;
        final boolean disabled;
        State(String runtime,String token,int pid,long beganAt,boolean disabled,int status){this.runtime=runtime;this.token=token;this.pid=pid;this.beganAt=beganAt;this.disabled=disabled;this.status=status;}
    }

    NativeRuntimeGuard(File directory,String runtime){
        if(runtime==null||!runtime.matches("[A-Za-z0-9._:-]{1,80}"))throw new IllegalArgumentException("Invalid native runtime identity.");
        this.file=new File(directory,"native-runtime-guard.bin");this.runtime=runtime;
    }
    State state() throws IOException {synchronized(LOCK){State state=read();return state!=null&&runtime.equals(state.runtime)?state:null;}}

    /** Only Android-confirmed native exits from this exact live lease disable a runtime. */
    boolean reconcile(Iterable<Exit> exits,long now) throws IOException {
        synchronized(LOCK){
            State state=state();
            if(state==null)return true;
            if(state.disabled)return false;
            if(now<state.beganAt)return true;
            for(Exit exit:exits){
                if(exit.mainProcess&&exit.pid==state.pid&&exit.reason==NATIVE_CRASH&&exit.timestamp>=state.beganAt&&exit.timestamp<=now&&exit.timestamp-state.beganAt<=MAX_EXECUTION_MS){
                    write(new State(runtime,state.token,state.pid,state.beganAt,true,exit.status));return false;
                }
            }
            return true;
        }
    }
    String begin(int pid,long now) throws IOException {
        if(pid<=0||now<=0)throw new IOException("Invalid native execution identity.");
        synchronized(LOCK){
            State state=state();if(state!=null&&state.disabled)throw new IOException("Native analysis is disabled for this runtime. Resume in compatibility mode.");
            String token=UUID.randomUUID().toString();write(new State(runtime,token,pid,now,false,0));return token;
        }
    }
    /** A retiring service cannot clear the lease belonging to its replacement. */
    void end(String token) throws IOException {
        if(token==null)return;
        synchronized(LOCK){
            State state=state();
            if(state!=null&&!state.disabled&&token.equals(state.token)&&!file.delete()&&file.exists())throw new IOException("The native execution marker could not be released.");
        }
    }
    private State read() throws IOException {
        if(!file.exists())return null;
        if(file.length()<1||file.length()>MAX_BYTES)throw new IOException("The native execution marker is invalid.");
        try(DataInputStream in=new DataInputStream(new ByteArrayInputStream(Files.readAllBytes(file.toPath())))){
            if(in.readInt()!=MAGIC)throw new IOException("The native execution marker is invalid.");
            String version=in.readUTF(),token=in.readUTF();int pid=in.readInt();long time=in.readLong();boolean disabled=in.readBoolean();int status=in.readInt();
            if(!version.matches("[A-Za-z0-9._:-]{1,80}")||!token.matches("[a-f0-9-]{36}")||pid<=0||time<=0||in.read()!=-1)throw new IOException("The native execution marker is invalid.");
            return new State(version,token,pid,time,disabled,status);
        }
    }
    private void write(State state) throws IOException {
        File directory=file.getParentFile();if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Native compatibility state could not be saved.");
        File temporary=File.createTempFile(".native-runtime-", ".tmp",directory);
        try{
            try(FileOutputStream out=new FileOutputStream(temporary);DataOutputStream data=new DataOutputStream(out)){
                data.writeInt(MAGIC);data.writeUTF(state.runtime);data.writeUTF(state.token);data.writeInt(state.pid);data.writeLong(state.beganAt);data.writeBoolean(state.disabled);data.writeInt(state.status);data.flush();out.getFD().sync();
            }
            Files.move(temporary.toPath(),file.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        }finally{temporary.delete();}
    }
}
