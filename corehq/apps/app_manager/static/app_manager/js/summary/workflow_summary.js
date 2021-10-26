hqDefine('app_manager/js/summary/workflow_summary',[
    'jquery',
    'underscore',
    'knockout',
    'hqwebapp/js/initial_page_data',
    'hqwebapp/js/assert_properties',
    'app_manager/js/summary/models',
    'app_manager/js/menu',  // enable lang switcher and "Updates to publish" banner
    'hqwebapp/js/knockout_bindings.ko', // popover
    'hqwebapp/js/components.ko',    // search box
], function ($, _, ko, initialPageData, assertProperties, models) {

    $(function () {
        let summaryMenu = models.menuModel({
            items: [],
            viewAllItems: gettext("App Workflow"),
        });

        let workflowSummaryContent = models.contentModel({
            form_name_map: initialPageData.get("form_name_map"),
            lang: initialPageData.get("lang"),
            langs: initialPageData.get("langs"),
            read_only: initialPageData.get("read_only"),
            appId: initialPageData.get("app_id"),
        });
        let workflowSummaryController = models.controlModel({
            visibleAppIds: initialPageData.get("app_id"),
            versionUrlName: 'app_workflow_summary',
            query_label: gettext("Filter"),
            onQuery: function (query) {
                console.log(query);
            },
            onSelectMenuItem: function (selectedId) {
                console.log(selectedId);
            },
        })
        $("#app-workflow-summary").koApplyBindings(workflowSummaryController);
        models.initVersionsBox(
            $("#version-selector"),
            {id: initialPageData.get("app_id"), text: initialPageData.get("app_version")}
        );
        models.initMenu([workflowSummaryContent], summaryMenu);
        models.initSummary(workflowSummaryContent, workflowSummaryController, "#workflow-summary");
    });
});
