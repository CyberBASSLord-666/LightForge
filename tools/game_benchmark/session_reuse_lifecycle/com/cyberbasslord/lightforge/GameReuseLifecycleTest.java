package com.cyberbasslord.lightforge;

import ai.onnxruntime.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.json.*;

/** Executes generated candidate ownership/control flow with synthetic ORT boundaries. */
public final class GameReuseLifecycleTest {
    private static File models;
    private static final JSONArray results=new JSONArray();
    private interface Test {void run()throws Exception;}
    private static Object field(NativeGame engine,String name)throws Exception {
        Field value=NativeGame.class.getDeclaredField(name);value.setAccessible(true);return value.get(engine);
    }
    @SuppressWarnings("unchecked") private static Map<String,OrtSession> sessions(NativeGame engine)throws Exception{return (Map<String,OrtSession>)field(engine,"sessions");}
    private static NativeGame fresh()throws Exception{return new NativeGame(models);}
    private static float[] pcm(int passage){return new float[(passage<2?14:2)*44100];}
    private static JSONArray predict(NativeGame engine,int passage,NativeGame.Listener listener,NativeGame.Cancellation cancellation)throws Exception {
        return engine.predict(pcm(passage),0,2025L+passage*104729L,listener,cancellation);
    }
    private static Throwable fails(Test action,String message)throws Exception {
        try{action.run();}catch(Exception|Error failure){return failure;}
        throw new AssertionError("Expected failure: "+message);
    }
    private static void terminal(NativeGame engine)throws Exception {
        int created=Control.created("session"),runs=Control.runCalls;
        fails(()->predict(engine,0,null,null),"terminal engine accepted prediction");
        Control.check(Control.created("session")==created&&Control.runCalls==runs,"Terminal engine created or ran resources");
    }
    private static void retired(NativeGame engine)throws Exception {
        engine.close();Control.check(engine.isRetired(),"Successful drain was not retired");Control.allAttempted();
    }
    private static void join(Thread thread)throws Exception {
        thread.join(5000);Control.check(!thread.isAlive(),"Worker deadlock");
    }
    private static void test(String name,Test test)throws Exception {
        Control.reset();test.run();
        results.put(new JSONObject().put("case",name).put("passed",true).put("sessionAttempts",Control.sessionAttempts)
            .put("sessionsCreated",Control.created("session")).put("sessionsCloseAttempts",Control.closed("session"))
            .put("runCalls",Control.runCalls).put("terminationRequests",Control.terminations));
    }
    private static void assertFreshAfterFailure()throws Exception {
        NativeGame fresh=fresh();Control.check(sessions(fresh).isEmpty(),"Fresh engine retained sessions");fresh.close();
        Control.check(fresh.isRetired(),"Fresh empty engine cannot close");
    }
    public static void main(String[] args)throws Exception {
        models=new File(args[0]);
        test("two_passages_reuse_five_sessions_and_fresh_run_options",()->{
            NativeGame engine=fresh();
            for(int passage=0;passage<2;passage++){
                JSONArray notes=predict(engine,passage,null,null);
                Control.check(notes.length()==1,"Synthetic fixture inference did not complete");
                Control.check(Control.created("session")==5&&Control.closed("session")==0,"Sessions not retained");
                Control.check(Control.created("runOptions")==passage+1&&Control.closed("runOptions")==passage+1,"Per-passage run handle lifetime");
                Control.check(!engine.isRetired(),"Open retained engine claims retired");
            }
            Control.check(Control.runCalls==24&&Control.prepareCalls==2,"Full unchanged 12-call path or model preparation skipped");
            retired(engine);terminal(engine);assertFreshAfterFailure();
        });
        test("empty_close_idempotent",()->{NativeGame engine=fresh();retired(engine);engine.close();Control.allAttempted();});
        test("android_constructor_forbidden",()->{fails(()->new NativeGame(new android.content.Context()),"Android context accepted");Control.check(Control.resources.isEmpty(),"Android constructed native resource");});
        for(int n=1;n<=5;n++){final int attempt=n;test("session_constructor_failure_"+n,()->{
            NativeGame engine=fresh();Control.failSessionAttempt=attempt;fails(()->predict(engine,0,null,null),"session construction");
            Control.check(Control.created("session")==attempt-1,"Partial creation count");retired(engine);terminal(engine);
        });}
        for(int n=1;n<=12;n++){final int call=n;test("inference_call_failure_"+n,()->{
            NativeGame engine=fresh();Control.failRunCall=call;fails(()->predict(engine,0,null,null),"graph run");
            Control.check(Control.runCalls==call,"Ran after graph failure");retired(engine);terminal(engine);
        });}
        test("second_passage_preparation_failure_drains_cached_sessions",()->{
            NativeGame engine=fresh();predict(engine,0,null,null);Control.failPrepareCall=2;
            fails(()->predict(engine,1,null,null),"preparation failure");retired(engine);terminal(engine);
        });
        for(String kind:new String[]{"runOptions","sessionOptions","tensor","result","session"}){
            for(boolean asError:new boolean[]{false,true})test(kind+"_retirement_"+(asError?"error":"exception"),()->{
                NativeGame engine=fresh();Control.failCloseKind=kind;Control.failCloseOrdinal=1;Control.failCloseWithError=asError;
                if(kind.equals("session")){predict(engine,0,null,null);engine.close();}
                else fails(()->predict(engine,0,null,null),"retirement failure");
                engine.close();Control.check(!engine.isRetired(),"Failed retirement incorrectly confirmed");
                Control.allAttempted();terminal(engine);assertFreshAfterFailure();
            });
        }
        test("invalid_second_passage_drains_cached_sessions",()->{
            NativeGame engine=fresh();predict(engine,0,null,null);
            fails(()->engine.predict(new float[1],0,2025+104729,null,null),"wrong source clock");retired(engine);terminal(engine);
        });
        test("source_passage_count_bound",()->{
            NativeGame engine=fresh();predict(engine,0,null,null);predict(engine,1,null,null);
            fails(()->predict(engine,2,null,null),"source count exceeded");retired(engine);terminal(engine);
        });
        test("wrong_owner_thread_drains_cached_sessions",()->{
            NativeGame engine=fresh();predict(engine,0,null,null);AtomicReference<Throwable> failure=new AtomicReference<>();
            Thread worker=new Thread(()->{try{predict(engine,1,null,null);}catch(Throwable error){failure.set(error);}});
            worker.start();join(worker);Control.check(failure.get() instanceof IOException,"Cross-thread prediction not rejected");retired(engine);terminal(engine);
        });
        test("cancel_before_first_prediction",()->{
            NativeGame engine=fresh();engine.cancel();fails(()->predict(engine,0,null,null),"cancelled prediction");
            Control.check(Control.created("session")==0,"Resources created after cancellation");retired(engine);
        });
        test("idle_cancel_drains_five_sessions",()->{
            NativeGame engine=fresh();predict(engine,0,null,null);engine.cancel();Control.allAttempted();
            Control.check(!engine.isRetired(),"Cancel must not imply close");retired(engine);terminal(engine);
        });
        for(boolean close:new boolean[]{false,true})test("cross_thread_"+(close?"close":"cancel")+"_during_run",()->{
            NativeGame engine=fresh();Control.blockRun=true;AtomicReference<Throwable> error=new AtomicReference<>();
            Thread canceller=new Thread(()->{try{Control.await(Control.runEntered);if(close)engine.close();else engine.cancel();}catch(Throwable e){error.set(e);}});
            canceller.start();fails(()->predict(engine,0,null,null),"concurrent cancellation");join(canceller);
            Control.check(error.get()==null,"Canceller failed: "+error.get());Control.check(Control.terminations>0,"Active run did not receive terminate");retired(engine);terminal(engine);
        });
        for(boolean close:new boolean[]{false,true})test("reentrant_listener_"+(close?"close":"cancel"),()->{
            NativeGame engine=fresh();AtomicBoolean once=new AtomicBoolean();
            fails(()->predict(engine,0,(progress,message)->{
                if(message.equals("Singing features recovered")&&once.compareAndSet(false,true)){
                    if(close)engine.close();else engine.cancel();
                    Control.check(Control.closed("session")==0&&Control.closed("runOptions")==0,"Reentrant cancellation retired outer resources");
                }
            },null),"listener cancellation");Control.check(once.get(),"Listener boundary not reached");retired(engine);terminal(engine);
        });
        test("reentrant_prediction_from_listener_keeps_outer_handle",()->{
            NativeGame engine=fresh();AtomicBoolean once=new AtomicBoolean();
            fails(()->predict(engine,0,(progress,message)->{
                if(message.equals("Singing features recovered")&&once.compareAndSet(false,true))try{
                    Object owner=field(engine,"activeRun");
                    fails(()->engine.predict(null,9,-1,null,null),"nested prediction");
                    Control.check(field(engine,"activeRun")==owner&&Control.closed("runOptions")==0,"Nested prediction stole outer handle");
                    Control.check(Control.closed("session")==0,"Nested prediction drained outer sessions");
                }catch(Exception error){throw new AssertionError(error);}
            },null),"outer cancellation");Control.check(once.get(),"Reentrant listener not reached");retired(engine);terminal(engine);
        });
        test("reentrant_prediction_from_cancellation_keeps_outer_handle",()->{
            NativeGame engine=fresh();AtomicBoolean once=new AtomicBoolean();
            fails(()->predict(engine,0,null,()->{
                try {
                    Object owner=field(engine,"activeRun");
                    if(owner!=null&&once.compareAndSet(false,true)){
                        fails(()->engine.predict(null,9,-1,null,null),"nested cancellation prediction");
                        Control.check(field(engine,"activeRun")==owner&&Control.closed("runOptions")==0,"Cancellation callback stole outer handle");
                    }
                    return false;
                }catch(Exception error){throw new AssertionError(error);}
            }),"outer cancellation");Control.check(once.get(),"Reentrant cancellation not reached");retired(engine);terminal(engine);
        });
        test("listener_exception_drains_sessions",()->{
            NativeGame engine=fresh();fails(()->predict(engine,0,(progress,message)->{if(message.equals("Singing features recovered"))throw new IllegalStateException("Injected listener failure");},null),"listener exception");retired(engine);terminal(engine);
        });
        test("cancellation_callback_exception_drains_retained_sessions",()->{
            NativeGame engine=fresh();predict(engine,0,null,null);
            fails(()->predict(engine,1,null,()->{throw new IllegalStateException("Injected callback failure");}),"callback exception");retired(engine);terminal(engine);
        });
        test("cancel_during_partial_constructor_retires_returned_handle",()->{
            NativeGame engine=fresh();Control.beforeCreate=()->{if(Control.sessionAttempts==3)engine.cancel();};
            fails(()->predict(engine,0,null,null),"constructor cancellation");
            Control.check(Control.created("session")==3&&Control.closed("session")==3,"Post-cancel constructor handle not retired");retired(engine);
        });
        test("idle_destructor_blocks_close_but_not_retirement_query",()->{
            NativeGame engine=fresh();predict(engine,0,null,null);AtomicReference<Throwable> error=new AtomicReference<>();
            Control.beforeSessionClose=()->{Control.closeEntered.countDown();Control.await(Control.closeAllowed);};
            Thread closer=new Thread(()->{try{engine.close();}catch(Throwable e){error.set(e);}});closer.start();
            Control.await(Control.closeEntered);
            Control.check(closer.isAlive(),"Idle destructor did not pause");
            AtomicReference<Boolean> reported=new AtomicReference<>();Thread query=new Thread(()->reported.set(engine.isRetired()));
            query.start();join(query);Control.check(Boolean.FALSE.equals(reported.get()),"Retirement query blocked or prematurely true");
            Control.closeAllowed.countDown();join(closer);Control.check(error.get()==null,"Idle close failed");retired(engine);
        });
        test("reentrant_idle_destructor_close_is_not_double_drain",()->{
            NativeGame engine=fresh();predict(engine,0,null,null);Control.beforeSessionClose=()->engine.close();retired(engine);
            Control.check(Control.closed("session")==5,"Reentrant idle close double drain");
        });
        test("reentrant_run_destructor_cancellation_does_not_terminate_retiring_handle",()->{
            NativeGame engine=fresh();Control.beforeRunClose=()->{
                Control.check(field(engine,"activeRun")==null,"Run handle still attached at destructor");engine.cancel();
            };
            // Cancellation occurs during successful-passage cleanup, after predict's
            // final check: return may be successful, but the instance is terminal.
            predict(engine,0,null,null);Control.check(Control.terminations==0,"Detached handle terminated while retiring");retired(engine);terminal(engine);
        });
        for(boolean clearFailure:new boolean[]{false,true})test("unexpected_drain_"+(clearFailure?"clear":"iteration")+"_error_is_unconfirmed",()->{
            NativeGame engine=fresh();predict(engine,0,null,null);
            Map<String,OrtSession> original=sessions(engine);
            Map<String,OrtSession> exploding=new LinkedHashMap<String,OrtSession>(original){
                @Override public Collection<OrtSession> values(){if(!clearFailure)throw new AssertionError("Injected iterator failure");return super.values();}
                @Override public void clear(){if(clearFailure)throw new AssertionError("Injected clear failure");super.clear();}
            };
            Field map=NativeGame.class.getDeclaredField("sessions");map.setAccessible(true);map.set(engine,exploding);
            fails(()->engine.close(),"unexpected drain Error");Control.check(!engine.isRetired(),"Unexpected drain confirmed ownership");
            Control.check(Boolean.TRUE.equals(field(engine,"retirementUnconfirmed")),"Unexpected drain did not poison retirement");
            // Ownership is explicitly unconfirmed: no retry or reuse is permitted.
            assertFreshAfterFailure();
        });
        JSONObject output=new JSONObject().put("schema","lightforge.game-session-reuse-mock-lifecycle.v1")
            .put("status","MOCK_BOUNDARIES_PASSED").put("cases",results).put("caseCount",results.length())
            .put("actualJvmExecution",true).put("generatedLifecycleExecuted",true).put("modelPreparationSubstituted",true)
            .put("syntheticOrtBoundaries",true).put("nativeJniLifecycleQualified",false).put("cudaExecuted",false)
            .put("withinProviderParityProven",false).put("benchmarkTimingAdmitted",false).put("qualityApproved",false)
            .put("target75Proven",false).put("appLifecycleEquivalent",false).put("releaseAuthorized",false);
        System.out.println(output.toString(2));
    }
}
