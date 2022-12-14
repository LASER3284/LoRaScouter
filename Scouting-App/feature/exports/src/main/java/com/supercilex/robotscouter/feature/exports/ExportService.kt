package com.supercilex.robotscouter.feature.exports

import android.app.IntentService
import android.content.ContentValues
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.view.View
import androidx.annotation.RequiresApi
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.google.android.gms.tasks.Tasks
import com.google.firebase.firestore.DocumentSnapshot
import com.supercilex.robotscouter.Bridge
import com.supercilex.robotscouter.ExportServiceCompanion
import com.supercilex.robotscouter.ExportServiceCompanion.Companion.PERMS_RC
import com.supercilex.robotscouter.ExportServiceCompanion.Companion.perms
import com.supercilex.robotscouter.core.CrashLogger
import com.supercilex.robotscouter.core.InvocationMarker
import com.supercilex.robotscouter.core.RobotScouter
import com.supercilex.robotscouter.core.data.getTeamListExtra
import com.supercilex.robotscouter.core.data.logExport
import com.supercilex.robotscouter.core.data.model.getScouts
import com.supercilex.robotscouter.core.data.model.getTemplatesQuery
import com.supercilex.robotscouter.core.data.model.scoutParser
import com.supercilex.robotscouter.core.data.putExtra
import com.supercilex.robotscouter.core.data.shouldShowRatingDialog
import com.supercilex.robotscouter.core.data.teams
import com.supercilex.robotscouter.core.data.waitForChange
import com.supercilex.robotscouter.core.fastAddOnSuccessListener
import com.supercilex.robotscouter.core.isOffline
import com.supercilex.robotscouter.core.isOnline
import com.supercilex.robotscouter.core.model.Scout
import com.supercilex.robotscouter.core.model.Team
import com.supercilex.robotscouter.core.model.TemplateType
import com.supercilex.robotscouter.core.ui.hasPerms
import com.supercilex.robotscouter.core.ui.requestPerms
import com.supercilex.robotscouter.core.ui.snackbar
import com.supercilex.robotscouter.shared.RatingDialog
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.tasks.asTask
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withTimeout
import java.io.File
import java.io.OutputStreamWriter
import java.io.BufferedWriter
import java.io.BufferedOutputStream
import java.util.concurrent.TimeUnit
import com.supercilex.robotscouter.R as RC
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.JsonArray
import com.google.gson.JsonElement
import android.content.ContentUris
import com.supercilex.robotscouter.core.data.safeCreateNewFile
import java.io.FileWriter

@Bridge
class ExportService : IntentService(TAG) {
    init {
        setIntentRedelivery(true)
    }

    override fun onHandleIntent(intent: Intent?) {
        val notificationManager = ExportNotificationManager(this)

        val teams: List<Team> = intent?.getTeamListExtra().orEmpty().sorted()
        val json: Boolean = intent?.getBooleanExtra("json", false) == true

        val chunks = teams.chunked(SYNCHRONOUS_QUERY_CHUNK)
        notificationManager.onStartLoading(chunks.size)

        if(json) {
            onHandleScouts(notificationManager, json, chunks.map {
                notificationManager.loading(it)

                runBlocking {
                    it.map { async { it.getScouts() } }.awaitAll()
                }.also { notificationManager.onChunkLoaded() }
            }.flatten().withIndex().associate {
                teams[it.index] to it.value
            })
            return
        }

        try {
            onHandleScouts(notificationManager, json, chunks.map {
                notificationManager.loading(it)

                runBlocking {
                    withTimeout(TimeUnit.MINUTES.toMillis(TIMEOUT)) {
                        it.map { async { it.getScouts() } }.awaitAll()
                    }
                }.also { notificationManager.onChunkLoaded() }
            }.flatten().withIndex().associate {
                teams[it.index] to it.value
            })
        } catch (t: Throwable) {
            notificationManager.abortCritical(t)
        }
    }

    private fun onHandleScouts(
            notificationManager: ExportNotificationManager,
            exportJSON: Boolean,
            newScouts: Map<Team, List<Scout>>
    ) {
        if (newScouts.values.all { it.isEmpty() }) {
            notificationManager.stopEmpty()
            return
        }

        val zippedScouts = zipScouts(newScouts)

        val exportFolder = if (Build.VERSION.SDK_INT >= 29) {
            File(filesDir, "Documents/Export_${System.currentTimeMillis()}")
        } else {
            @Suppress("DEPRECATION")
            val downloadsDir = Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_DOWNLOADS)
            if(exportJSON) {
                File(downloadsDir, "Robot Scouter")
            }
            else {
                File(downloadsDir, "Robot Scouter/Export_${System.currentTimeMillis()}")
            }
        }

        notificationManager.loaded(zippedScouts.size, newScouts.keys, exportFolder)

        // If we're exporting as JSON, we'll need to do this is a bit differently than the file-by-file spreadsheet exports.
        if(exportJSON) {
            val rootDir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), "Robot Scouter")
            if(!rootDir.exists()) {
                rootDir.mkdirs();
            }

            val json_elements = runBlocking {
                val templateNames = getTemplateNames(zippedScouts.keys)
                withTimeout(TimeUnit.MINUTES.toMillis(5)) {
                    zippedScouts.map { (templateId, scouts) ->
                        async {
                            if (notificationManager.isStopped()) return@async null

                            try {
                                TemplateExporter(
                                        scouts,
                                        notificationManager,
                                        exportFolder,
                                        templateNames[templateId]
                                ).getJson()
                            } catch (t: Throwable) {
                                notificationManager.abortCritical(t)
                                throw CancellationException()
                            }
                        }
                    }.awaitAll()
                }
            }.filterNotNull().first()


            val gson = GsonBuilder().setPrettyPrinting().serializeNulls().disableHtmlEscaping().create()

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val resolver = RobotScouter.contentResolver

                val contentUri = MediaStore.Downloads.EXTERNAL_CONTENT_URI;
                val selection = MediaStore.MediaColumns.RELATIVE_PATH + "=?"
                val selectionArgs = arrayOf<String>(Environment.DIRECTORY_DOWNLOADS + "/Robot Scouter/")
                val cursor = resolver.query(contentUri, null, selection, selectionArgs, null)
                var uri: Uri? = null
                if (cursor?.getCount() != 0) {
                    while (cursor?.moveToNext() == true) {
                        val fileName = cursor.getString(cursor.getColumnIndex(MediaStore.MediaColumns.DISPLAY_NAME))

                        if (fileName.equals("RadioScout.json")) {
                            val id = cursor.getLong(cursor.getColumnIndex(MediaStore.MediaColumns._ID))

                            uri = ContentUris.withAppendedId(contentUri, id)

                            break
                        }
                    }
                }

                if(uri == null) {
                    val contentValues = ContentValues();
                    contentValues.put(MediaStore.MediaColumns.DISPLAY_NAME, "RadioScout");
                    contentValues.put(MediaStore.MediaColumns.MIME_TYPE, "application/json");
                    contentValues.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/Robot Scouter");
                    uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues);
                }

                if(uri == null) {
                    throw Exception()
                }

                val fos = resolver.openOutputStream(uri, "rwt");
                OutputStreamWriter(fos, Charsets.UTF_8).use { osw ->
                    BufferedWriter(osw).use { bf -> bf.write(gson.toJson(json_elements)) }
                }
            }
            else {
                val JSONFile = File(rootDir, "RadioScout.json")
                if(JSONFile.exists()) {
                    JSONFile.delete();
                }
                JSONFile.writeText(gson.toJson(json_elements))
            }

            return
        }

        val outboundUris = runBlocking {
            val templateNames = getTemplateNames(zippedScouts.keys)
            withTimeout(TimeUnit.MINUTES.toMillis(TIMEOUT)) {
                zippedScouts.map { (templateId, scouts) ->
                    async {
                        if (notificationManager.isStopped()) return@async null

                        try {
                            TemplateExporter(
                                    scouts,
                                    notificationManager,
                                    exportFolder,
                                    templateNames[templateId]
                            ).export()
                        } catch (t: Throwable) {
                            notificationManager.abortCritical(t)
                            throw CancellationException()
                        }
                    }
                }.awaitAll()
            }
        }.filterNotNull()

        if (Build.VERSION.SDK_INT >= 29) {
            try {
                for ((file, uri) in outboundUris.flatten()) {
                    copyFileToMediaStore(file, uri)
                }
            } finally {
                exportFolder.deleteRecursively()
            }
        }
    }

    @RequiresApi(29)
    private fun copyFileToMediaStore(sheetFile: File, sheetUri: Uri) {
        val resolver = RobotScouter.contentResolver
        checkNotNull(resolver.openOutputStream(sheetUri)).use { output ->
            sheetFile.inputStream().use { input ->
                input.copyTo(output)
            }
        }

        resolver.update(sheetUri, ContentValues().apply {
            put(MediaStore.MediaColumns.IS_PENDING, 0)
        }, null, null)
    }

    private suspend fun getTemplateNames(templateIds: Set<String>): Map<String, String?> {
        val unknownTemplateName: String = getString(R.string.export_unknown_template_title)

        val templatesSnapshot: List<DocumentSnapshot> = try {
            getTemplatesQuery().get().await().documents
        } catch (e: Exception) {
            CrashLogger.onFailure(InvocationMarker(e))
            emptyList()
        }
        val allPossibleTemplateNames: Map<String, String?> = templatesSnapshot.associate {
            scoutParser.parseSnapshot(it).let { it.id to it.name }
        }.toMutableMap().apply {
            putAll(TemplateType.values.associate {
                it.id.toString() to resources.getStringArray(RC.array.template_new_options)[it.id]
            })
        }

        val usedTemplates = mutableMapOf<String, Int>()
        return templateIds.associate {
            if (allPossibleTemplateNames.contains(it)) {
                it to allPossibleTemplateNames[it]
            } else {
                // User deleted template
                it to unknownTemplateName
            }
        }.mapValues { (_, name) ->
            if (name == null) return@mapValues null
            usedTemplates[name]?.let {
                usedTemplates[name] = it + 1
                "$name ($it)"
            } ?: run {
                usedTemplates[name] = 1
                name
            }
        }
    }

    private fun zipScouts(map: Map<Team, List<Scout>>): Map<String, Map<Team, List<Scout>>> {
        val zippedScouts = mutableMapOf<String, MutableMap<Team, MutableList<Scout>>>()
        for ((team, scouts) in map) {
            for (scout in scouts) {
                zippedScouts.getOrPut(scout.templateId) {
                    mutableMapOf()
                }.getOrPut(team) {
                    mutableListOf()
                }.add(scout)
            }
        }
        return zippedScouts
    }

    private fun ExportNotificationManager.abortCritical(t: Throwable) {
        if (t !is TimeoutCancellationException) CrashLogger(t)
        abort()
    }

    companion object : ExportServiceCompanion {
        private const val TAG = "ExportService"
        private const val SYNCHRONOUS_QUERY_CHUNK = 10
        private const val TIMEOUT = 10L

        private const val MIN_TEAMS_TO_RATE = 10

        override fun exportAndShareSpreadSheet(
                activity: FragmentActivity,
                teams: List<Team>,
                json: Boolean
        ): Boolean {
            if (!hasPerms(perms)) {
                activity.requestPerms(perms, R.string.export_write_storage_rationale, PERMS_RC)
                return false
            }

            activity.findViewById<View>(RC.id.root)
                    .snackbar(RobotScouter.getString(R.string.export_progress_hint))

            if (teams.isEmpty()) {
                getAllTeams()
            } else {
                Tasks.forResult(teams.toList())
            }.fastAddOnSuccessListener { exportedTeams ->
                exportedTeams.logExport()
                ContextCompat.startForegroundService(
                        RobotScouter,
                        Intent(RobotScouter, ExportService::class.java).putExtra(exportedTeams).putExtra("json", json)
                )
            }.addOnSuccessListener(activity) {
                if (it.size >= MIN_TEAMS_TO_RATE && isOnline && shouldShowRatingDialog) {
                    RatingDialog.show(activity.supportFragmentManager)
                }
            }

            return true
        }

        private fun getAllTeams() = GlobalScope.async { teams.waitForChange() }.asTask()
    }
}
