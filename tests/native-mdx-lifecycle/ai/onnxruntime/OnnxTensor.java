package ai.onnxruntime;
import java.nio.FloatBuffer;
public final class OnnxTensor implements AutoCloseable {
    final FloatBuffer values;
    private OnnxTensor(FloatBuffer values){this.values=values;}
    public static OnnxTensor createTensor(OrtEnvironment environment,FloatBuffer values,long[] dimensions){return new OnnxTensor(values);}
    public void close(){}
}
