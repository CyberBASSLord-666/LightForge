package ai.onnxruntime;
public final class OrtEnvironment {
    public static OrtEnvironment getEnvironment(){Control.beforeInitialization.run();return new OrtEnvironment();}
    public OrtSession createSession(String path,OrtSession.SessionOptions options)throws OrtException{
        Control.createEntered.countDown();if(Control.blockCreate)Control.await(Control.createAllowed);
        if(Control.failCreate)throw new OrtException("Simulated graph construction failure");return new OrtSession();
    }
}
