package com.cyberbasslord.lightforge;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.nio.channels.Pipe;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Actual instrumentation stop method, controlled real NIO; no device or model claim. */
public final class BackgroundObserverStopTest {
    private static int checks;
    private static final Method STOP;
    static {
        try{STOP=BackgroundInstrumentation.class.getDeclaredMethod("stopBalancedObserver");STOP.setAccessible(true);}
        catch(Exception error){throw new ExceptionInInitializerError(error);}
    }
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);checks++;}
    private static Object field(Object target,String name)throws Exception{
        Field field=BackgroundInstrumentation.class.getDeclaredField(name);field.setAccessible(true);return field.get(target);
    }
    private static void field(Object target,String name,Object value)throws Exception{
        Field field=BackgroundInstrumentation.class.getDeclaredField(name);field.setAccessible(true);field.set(target,value);
    }
    private static Throwable stop(BackgroundInstrumentation observer)throws Exception{
        try{STOP.invoke(observer);return null;}
        catch(InvocationTargetException error){return error.getCause();}
    }
    private static final class ReadFixture implements AutoCloseable {
        final BackgroundInstrumentation observer=new BackgroundInstrumentation();
        final Pipe pipe=Pipe.open();
        final CountDownLatch entered=new CountDownLatch(1);
        final AtomicReference<Throwable> readFailure=new AtomicReference<>();
        volatile int readValue=-1;
        final Thread reader;
        ReadFixture()throws Exception{
            reader=new Thread(()->{
                try{
                    ByteBuffer bytes=ByteBuffer.allocate(1);entered.countDown();
                    int read=pipe.source().read(bytes);
                    if(read==1)readValue=bytes.get(0)&255;
                }catch(Throwable error){
                    readFailure.set(error);
                    try{field(observer,"balancedObservationFailure",error);}catch(Exception reflection){throw new AssertionError(reflection);}
                }
            },"actual-instrumentation-stop-nio");
            field(observer,"balancedObserver",reader);reader.start();
            check(entered.await(2,TimeUnit.SECONDS),"NIO reader did not start");
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);boolean insideRead=false;
            while(System.nanoTime()<deadline&&!insideRead){
                for(StackTraceElement frame:reader.getStackTrace())
                    if(frame.getClassName().endsWith("SourceChannelImpl")&&frame.getMethodName().equals("read"))insideRead=true;
                if(!insideRead)Thread.sleep(1);
            }
            check(insideRead,"Fixture did not observe an actual blocking NIO read");
        }
        void unblock()throws Exception{if(pipe.source().isOpen())pipe.sink().write(ByteBuffer.wrap(new byte[]{42}));}
        public void close()throws Exception{
            unblock();reader.join(2000);
            pipe.source().close();pipe.sink().close();
            check(!reader.isAlive(),"Fixture leaked its NIO reader");
        }
    }
    private static void inFlightReadFinishes()throws Exception{
        try(ReadFixture fixture=new ReadFixture()){
            AtomicReference<Throwable> outcome=new AtomicReference<>();
            CountDownLatch finished=new CountDownLatch(1);
            Thread stopper=new Thread(()->{
                try{outcome.set(stop(fixture.observer));}catch(Throwable error){outcome.set(error);}finally{finished.countDown();}
            },"actual-instrumentation-stop-caller");
            stopper.start();
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
            while(!(Boolean)field(fixture.observer,"balancedObserverStopped")&&System.nanoTime()<deadline)Thread.sleep(1);
            check((Boolean)field(fixture.observer,"balancedObserverStopped"),"Stop flag was not set before join");
            check(!finished.await(50,TimeUnit.MILLISECONDS),"Stop returned before its in-flight read finished");
            check(!fixture.reader.isInterrupted()&&fixture.pipe.source().isOpen(),"Normal stop interrupted the NIO read");
            fixture.unblock();
            check(finished.await(2,TimeUnit.SECONDS),"Stop did not join the completed read");stopper.join(2000);
            check(outcome.get()==null&&fixture.readFailure.get()==null,"Normal stop manufactured an observer failure");
            check(fixture.readValue==42&&!fixture.reader.isAlive(),"Stop failed to retain the complete read");
        }
    }
    private static void realFailuresRemainFailures()throws Exception{
        for(Throwable cause:new Throwable[]{new IOException("real status read failure"),new AssertionError("real lifecycle failure"),new InterruptedException("unexpected observer interruption")}){
            BackgroundInstrumentation observer=new BackgroundInstrumentation();
            Thread ended=new Thread(()->{});ended.start();ended.join();
            field(observer,"balancedObserver",ended);field(observer,"balancedObservationFailure",cause);
            Throwable outcome=stop(observer);
            check(outcome instanceof AssertionError&&outcome.getCause()==cause,"Stopping suppressed an existing observer failure");
        }
    }
    private static void stuckReadStillFailsAtFiveSeconds()throws Exception{
        try(ReadFixture fixture=new ReadFixture()){
            long began=System.nanoTime();Throwable outcome=stop(fixture.observer);
            long millis=TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-began);
            check(outcome instanceof AssertionError&&"Balanced observation thread did not stop".equals(outcome.getMessage()),"A stuck observer bypassed the stop timeout");
            check(millis>=4500&&millis<10000,"The existing five-second observer stop budget changed: "+millis);
            check(fixture.reader.isAlive()&&!fixture.reader.isInterrupted(),"Timeout interrupted or falsely retired the observer");
        }
    }
    public static void main(String[] args)throws Exception{
        inFlightReadFinishes();realFailuresRemainFailures();stuckReadStillFailsAtFiveSeconds();
        System.out.println("PASS: "+checks+" actual instrumentation observer stop checks; real NIO completion, preserved failures and bounded timeout");
    }
}
