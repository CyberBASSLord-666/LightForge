package ai.onnxruntime;
import java.nio.*;
public final class OnnxTensor extends Control.Resource implements OnnxValue {
    private final TensorInfo info;private final Buffer data;
    private OnnxTensor(OnnxJavaType type,Buffer data,long[] shape){super("tensor");info=new TensorInfo(type,shape);this.data=data;}
    public static OnnxTensor createTensor(OrtEnvironment environment,FloatBuffer data,long[] shape){return new OnnxTensor(OnnxJavaType.FLOAT,data,shape);}
    public static OnnxTensor createTensor(OrtEnvironment environment,LongBuffer data,long[] shape){return new OnnxTensor(OnnxJavaType.INT64,data,shape);}
    static OnnxTensor floats(float[] data,long... shape){return new OnnxTensor(OnnxJavaType.FLOAT,FloatBuffer.wrap(data),shape);}
    static OnnxTensor bools(byte[] data,long... shape){return new OnnxTensor(OnnxJavaType.BOOL,ByteBuffer.wrap(data),shape);}
    public TensorInfo getInfo(){usable();return info;}
    public FloatBuffer getFloatBuffer(){usable();return ((FloatBuffer)data).duplicate();}
    public ByteBuffer getByteBuffer(){usable();return ((ByteBuffer)data).duplicate();}
}
