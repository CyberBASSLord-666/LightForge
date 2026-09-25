package ai.onnxruntime;
import java.util.*;
public final class OrtEnvironment {
    public static OrtEnvironment getEnvironment(){return new OrtEnvironment();}
    public static EnumSet<OrtProvider> getAvailableProviders(){return EnumSet.allOf(OrtProvider.class);}
    public String getVersion(){return "1.25.1";}
    public OrtSession createSession(String path,OrtSession.SessionOptions options)throws Exception {
        options.usable();Control.sessionAttempts++;Control.beforeCreate.call();
        if(Control.sessionAttempts==Control.failSessionAttempt)throw new OrtException("Injected graph constructor failure");
        return new OrtSession(new java.io.File(path).getName().replace(".onnx",""));
    }
}
