package com.nautilus.validation

import android.app.Activity
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import app.tauri.annotation.Command
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

@TauriPlugin
class CredentialPlugin(activity: Activity) : Plugin(activity) {
  companion object {
    private const val KEYSTORE = "AndroidKeyStore"
    private const val KEY_ALIAS = "com.nautilus.validation.credentials.v1"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val IV_BYTES = 12
    private const val TAG_BYTES = 16
  }

  @Command
  fun encrypt(invoke: Invoke) {
    try {
      val args = invoke.getArgs()
      val plaintext = args.opt("plaintext") as? String
      val scope = args.opt("scope") as? String
      require(plaintext != null && !scope.isNullOrEmpty())

      val cipher = Cipher.getInstance(TRANSFORMATION)
      cipher.init(Cipher.ENCRYPT_MODE, encryptionKey())
      val iv = cipher.iv
      check(iv.size == IV_BYTES)
      cipher.updateAAD(scope.toByteArray(Charsets.UTF_8))
      val encrypted = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))
      val combined = ByteArray(iv.size + encrypted.size)
      iv.copyInto(combined)
      encrypted.copyInto(combined, iv.size)

      invoke.resolve(JSObject().put("ciphertext", Base64.encodeToString(combined, Base64.NO_WRAP)))
    } catch (_: Exception) {
      invoke.reject("无法安全保存密钥，请重试。")
    }
  }

  @Command
  fun decrypt(invoke: Invoke) {
    try {
      val args = invoke.getArgs()
      val ciphertext = args.opt("ciphertext") as? String
      val scope = args.opt("scope") as? String
      require(ciphertext != null && !scope.isNullOrEmpty())

      val combined = Base64.decode(ciphertext, Base64.NO_WRAP)
      require(combined.size >= IV_BYTES + TAG_BYTES)
      val cipher = Cipher.getInstance(TRANSFORMATION)
      cipher.init(Cipher.DECRYPT_MODE, decryptionKey(), GCMParameterSpec(TAG_BYTES * 8, combined, 0, IV_BYTES))
      cipher.updateAAD(scope.toByteArray(Charsets.UTF_8))
      val plaintext = cipher.doFinal(combined, IV_BYTES, combined.size - IV_BYTES)

      invoke.resolve(JSObject().put("plaintext", String(plaintext, Charsets.UTF_8)))
    } catch (_: Exception) {
      invoke.reject("无法读取已保存的密钥，请重新输入并保存。")
    }
  }

  private fun encryptionKey(): SecretKey {
    val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
    if (keyStore.containsAlias(KEY_ALIAS)) {
      return keyStore.getKey(KEY_ALIAS, null) as? SecretKey
        ?: error("Credential key unavailable")
    }
    val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
    generator.init(
      KeyGenParameterSpec.Builder(
        KEY_ALIAS,
        KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
      )
        .setKeySize(256)
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
        .build(),
    )
    return generator.generateKey()
  }

  private fun decryptionKey(): SecretKey {
    val keyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }
    return keyStore.getKey(KEY_ALIAS, null) as? SecretKey
      ?: error("Credential key unavailable")
  }
}
