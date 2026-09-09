package android.util;
public final class Base64 {
    public static final int DEFAULT=0;
    public static byte[] decode(String value,int flags){return java.util.Base64.getDecoder().decode(value);}
}
